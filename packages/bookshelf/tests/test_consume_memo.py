"""A warm cache answers a pinned read with no round trip.

Book identity for a pinned edition and a resource's hash never change,
so the facade remembers them on disk and a fresh process reuses them.
The latest edition is the one thing that can change, so it is always asked for.
"""

import hashlib
from pathlib import Path
from typing import Any

import httpx
import pytest

from bookshelf.cache import ContentCache
from bookshelf.facade import AsyncBookshelf, Bookshelf
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"
PAYLOAD = b"gas,year,value\nco2,2023,1.0\n"
CONTENT_HASH = f"sha256:{hashlib.sha256(PAYLOAD).hexdigest()}"

BOOK_ID = "0197a000-0000-7000-8000-0000000000b1"
BOOK_PAGE: dict[str, Any] = dict(
    payloads.BOOK_LIST,
    items=[dict(payloads.book_list_item(status="published", edition=2), id=BOOK_ID)],
    total=1,
)
ENTRIES_PAGE: dict[str, Any] = {
    "items": [
        {
            "entry_id": "0197a000-0000-7000-8000-0000000000e1",
            "tracking_id": payloads.RESOURCE_READ["tracking_id"],
            "name_in_book": "by_country",
            "type": "timeseries",
            "visibility": "org",
            "data_dictionary": None,
        }
    ],
    "next_cursor": None,
}
RESOURCE_READ: dict[str, Any] = dict(payloads.RESOURCE_READ, hash=CONTENT_HASH)
BOOK_PUBLISHED: dict[str, Any] = dict(
    payloads.BOOK_RESPONSE, id=BOOK_ID, edition=2, status="published", published_at=payloads.TS
)
BOOK_DRAFT: dict[str, Any] = dict(payloads.BOOK_RESPONSE, id=BOOK_ID, edition=2)


def _transport(recorded: list[httpx.Request], pages: list[Any]) -> httpx.MockTransport:
    remaining = list(pages)

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if not remaining:
            raise AssertionError(f"unexpected request {request.method} {request.url}")
        return httpx.Response(200, json=remaining.pop(0))

    return httpx.MockTransport(handler)


def _sync(
    recorded: list[httpx.Request],
    pages: list[Any],
    base_url: str = BASE_URL,
    book_ttl: float | None = None,
) -> Bookshelf:
    return Bookshelf(base_url, auth=None, book_ttl=book_ttl, transport=_transport(recorded, pages))


def _async(recorded: list[httpx.Request], pages: list[Any]) -> AsyncBookshelf:
    return AsyncBookshelf(BASE_URL, auth=None, async_transport=_transport(recorded, pages))


def test_a_pinned_edition_is_resolved_once_per_cache() -> None:
    first: list[httpx.Request] = []
    book = _sync(first, [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0", edition=2)
    assert [request.url.path for request in first] == ["/v1/books", f"/v1/books/{BOOK_ID}/entries"]

    second: list[httpx.Request] = []
    again = _sync(second, []).book("example", "v1.0.0", edition=2)

    assert second == []
    assert again.book_id == book.book_id
    assert again.entry_names == book.entry_names


def test_the_latest_edition_is_always_asked_for() -> None:
    _sync([], [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0")

    second: list[httpx.Request] = []
    _sync(second, [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0")

    assert [request.url.path for request in second] == ["/v1/books", f"/v1/books/{BOOK_ID}/entries"]


def test_a_remembered_book_is_scoped_to_its_server() -> None:
    _sync([], [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0", edition=2)

    other: list[httpx.Request] = []
    _sync(other, [BOOK_PAGE, ENTRIES_PAGE], "https://other.test").book(
        "example", "v1.0.0", edition=2
    )

    assert len(other) == 2


def test_a_missing_edition_is_not_remembered() -> None:
    empty = dict(payloads.BOOK_LIST)
    with pytest.raises(Exception, match="no published book"):
        _sync([], [empty]).book("example", "v1.0.0", edition=9)

    second: list[httpx.Request] = []
    with pytest.raises(Exception, match="no published book"):
        _sync(second, [empty]).book("example", "v1.0.0", edition=9)

    assert len(second) == 1


def test_a_cached_file_is_served_without_any_request(tmp_path: Path) -> None:
    ContentCache().put(CONTENT_HASH, PAYLOAD)
    first: list[httpx.Request] = []
    entry = _sync(first, [BOOK_PAGE, ENTRIES_PAGE, RESOURCE_READ]).book(
        "example", "v1.0.0", edition=2
    )["by_country"]
    assert entry.as_path().read_bytes() == PAYLOAD
    assert [request.url.path for request in first][-1].startswith("/v1/resources/")

    second: list[httpx.Request] = []
    entry = _sync(second, []).book("example", "v1.0.0", edition=2)["by_country"]

    assert entry.as_path().read_bytes() == PAYLOAD
    assert entry.type.value == "timeseries"
    assert second == []


@pytest.mark.asyncio
async def test_the_async_surface_reads_the_same_memory() -> None:
    ContentCache().put(CONTENT_HASH, PAYLOAD)
    _sync([], [BOOK_PAGE, ENTRIES_PAGE, RESOURCE_READ]).book("example", "v1.0.0", edition=2)[
        "by_country"
    ].as_path()

    recorded: list[httpx.Request] = []
    book = await _async(recorded, []).book("example", "v1.0.0", edition=2)
    path = await book["by_country"].as_path()

    assert path.read_bytes() == PAYLOAD
    assert recorded == []


def test_a_corrupt_record_is_dropped_and_asked_for_again() -> None:
    _sync([], [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0", edition=2)
    cache = ContentCache()
    (record,) = cache.metadata.base_dir.rglob("*.json")
    assert record.name == "v1.0.0_e002.json"
    record.write_text("{not json")

    second: list[httpx.Request] = []
    _sync(second, [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0", edition=2)

    assert len(second) == 2


def test_clearing_the_cache_forgets_the_records() -> None:
    _sync([], [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0", edition=2)
    cache = ContentCache()
    assert list(cache.metadata.base_dir.rglob("*.json"))

    cache.clear()

    assert not cache.metadata.base_dir.exists()


def test_an_expired_record_is_checked_with_one_request() -> None:
    _sync([], [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0", edition=2)

    checked: list[httpx.Request] = []
    book = _sync(checked, [BOOK_PUBLISHED], book_ttl=0).book("example", "v1.0.0", edition=2)
    assert [request.url.path for request in checked] == [f"/v1/books/{BOOK_ID}"]
    assert book.entry_names == ("by_country",)

    trusted: list[httpx.Request] = []
    _sync(trusted, []).book("example", "v1.0.0", edition=2)
    assert trusted == []


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(BOOK_DRAFT, id="no-longer-published"),
        pytest.param(payloads.problem(404, "Not Found", "gone"), id="deleted"),
    ],
)
def test_a_retracted_edition_is_resolved_afresh(answer: dict[str, Any]) -> None:
    _sync([], [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0", edition=2)

    recorded: list[httpx.Request] = []
    pages: list[Any] = [answer, BOOK_PAGE, ENTRIES_PAGE]
    remaining = list(pages)

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = remaining.pop(0)
        status = 404 if body.get("status") == 404 else 200
        return httpx.Response(status, json=body)

    bs = Bookshelf(BASE_URL, auth=None, book_ttl=0, transport=httpx.MockTransport(handler))
    bs.book("example", "v1.0.0", edition=2)

    assert [request.url.path for request in recorded] == [
        f"/v1/books/{BOOK_ID}",
        "/v1/books",
        f"/v1/books/{BOOK_ID}/entries",
    ]


def test_the_ttl_default_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _sync([], [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0", edition=2)
    monkeypatch.setenv("BOOKSHELF_CACHE_BOOK_TTL", "0")

    checked: list[httpx.Request] = []
    _sync(checked, [BOOK_PUBLISHED]).book("example", "v1.0.0", edition=2)

    assert len(checked) == 1


@pytest.mark.asyncio
async def test_the_async_surface_checks_an_expired_record_too() -> None:
    _sync([], [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0", edition=2)

    checked: list[httpx.Request] = []
    bs = AsyncBookshelf(
        BASE_URL, auth=None, book_ttl=0, async_transport=_transport(checked, [BOOK_PUBLISHED])
    )
    book = await bs.book("example", "v1.0.0", edition=2)

    assert [request.url.path for request in checked] == [f"/v1/books/{BOOK_ID}"]
    assert book.entry_names == ("by_country",)


def test_an_outage_during_the_recheck_serves_the_remembered_edition() -> None:
    _sync([], [BOOK_PAGE, ENTRIES_PAGE]).book("example", "v1.0.0", edition=2)

    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(500, json=payloads.problem(500, "Broken", "later"))

    bs = Bookshelf(BASE_URL, auth=None, book_ttl=0, transport=httpx.MockTransport(handler))
    book = bs.book("example", "v1.0.0", edition=2)

    assert book.entry_names == ("by_country",)
    assert {request.url.path for request in recorded} == {f"/v1/books/{BOOK_ID}"}

    checked: list[httpx.Request] = []
    _sync(checked, [BOOK_PUBLISHED], book_ttl=0).book("example", "v1.0.0", edition=2)
    assert len(checked) == 1


def test_a_bad_ttl_in_the_environment_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKSHELF_CACHE_BOOK_TTL", "soon")

    with pytest.warns(UserWarning, match="BOOKSHELF_CACHE_BOOK_TTL"):
        bs = _sync([], [])

    assert bs._book_ttl == 24 * 60 * 60


def test_a_version_that_flattens_onto_another_is_not_confused_with_it() -> None:
    plus = dict(BOOK_PAGE, items=[dict(BOOK_PAGE["items"][0], version="1.0.0+a")])
    _sync([], [plus, ENTRIES_PAGE]).book("example", "1.0.0+a", edition=2)

    recorded: list[httpx.Request] = []
    dash = dict(BOOK_PAGE, items=[dict(BOOK_PAGE["items"][0], version="1.0.0-a")])
    _sync(recorded, [dash, ENTRIES_PAGE]).book("example", "1.0.0-a", edition=2)

    assert len(recorded) == 2
