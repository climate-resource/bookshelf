"""The producer surface the public facades bind to, reached through the facade itself."""

import inspect
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.facade import AsyncLiveSink, LiveSink
from bookshelf.facade import AsyncBookshelf, Bookshelf
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.record import RecordingBookshelf, RecordingSink
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"
TRACKING_ID = "0197a000-0000-7000-8000-000000000001"

REGISTERED_ONE: dict[str, Any] = {
    "activity_created": False,
    "atomic": True,
    "registered": [
        {
            "index": 0,
            "status": "created",
            "outcome": {"status": "created", "tracking_id": TRACKING_ID},
        }
    ],
}


def _transport(recorded: list[httpx.Request], status: int, payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)  # type: ignore[no-any-return]


def _sync(recorded: list[httpx.Request], status: int, payload: Any) -> Bookshelf:
    return Bookshelf(BASE_URL, auth=None, transport=_transport(recorded, status, payload))


def _async(recorded: list[httpx.Request], status: int, payload: Any) -> AsyncBookshelf:
    return AsyncBookshelf(
        BASE_URL, auth=None, async_transport=_transport(recorded, status, payload)
    )


def test_draft_book_wraps_the_optional_strings_the_api_takes_as_models() -> None:
    """The DOI, the licence and the bundle hash each arrive as a plain string on the wire."""
    recorded: list[httpx.Request] = []

    with _sync(recorded, 201, payloads.BOOK_DETAIL) as client:
        draft = client.draft_book(
            "primap-hist",
            version="1.0.0",
            citation_doi="10.5281/zenodo.1",
            license="CC-BY-4.0",
            bundle_hash="a" * 64,
            data_dictionary=[models.DataDictionaryEntry(name="region", role="dimension")],
        )

    assert draft.metadata.series_name == "primap-hist"
    request = recorded[0]
    assert (request.method, request.url.path) == ("POST", "/v1/books")
    body = _body(request)
    assert body["citation_doi"] == "10.5281/zenodo.1"
    assert body["license"] == "CC-BY-4.0"
    assert body["bundle_hash"] == "a" * 64
    assert body["data_dictionary"] == [{"name": "region", "role": "dimension"}]


def test_draft_book_sends_no_wrapper_for_an_omitted_string() -> None:
    """An omitted DOI, licence or bundle hash stays null rather than arriving as an empty model."""
    recorded: list[httpx.Request] = []

    with _sync(recorded, 201, payloads.BOOK_DETAIL) as client:
        client.draft_book("primap-hist", version="1.0.0")

    body = _body(recorded[0])
    assert body["citation_doi"] is None
    assert body["license"] is None
    assert body["bundle_hash"] is None
    assert body["visibility"] == "hidden"


def test_draft_book_carries_an_explicit_tier() -> None:
    recorded: list[httpx.Request] = []

    with _sync(recorded, 201, payloads.BOOK_DETAIL) as client:
        client.draft_book("primap-hist", version="1.0.0", visibility="public")

    assert _body(recorded[0])["visibility"] == "public"


def test_register_external_catalogues_the_pointer() -> None:
    recorded: list[httpx.Request] = []

    with _sync(recorded, 200, REGISTERED_ONE) as client:
        resource = client.register_external(
            type="tabular",
            uri="https://example.invalid/data.csv",
            logical_key="raw/data.csv",
            tags=["raw"],
        )

    assert resource.tracking_id == UUID(TRACKING_ID)
    request = recorded[0]
    assert (request.method, request.url.path) == ("POST", "/v1/resources/registrations")
    item = _body(request)["items"][0]
    assert item["external_uri"] == "https://example.invalid/data.csv"
    assert item["type"] == "tabular"
    assert item["logical_key"] == "raw/data.csv"
    assert item["tags"] == ["raw"]
    assert item["visibility"] == "hidden"


def test_register_external_raises_when_the_batch_comes_back_empty() -> None:
    recorded: list[httpx.Request] = []

    with (
        _sync(recorded, 200, payloads.REGISTERED) as client,
        pytest.raises(BookshelfError, match="no registration outcome"),
    ):
        client.register_external(type="tabular", uri="https://example.invalid/data.csv")


async def test_the_async_producer_surface_matches_the_sync_one() -> None:
    drafted: list[httpx.Request] = []
    async with _async(drafted, 201, payloads.BOOK_DETAIL) as client:
        draft = await client.draft_book(
            "primap-hist",
            version="1.0.0",
            license="CC-BY-4.0",
        )
    assert draft.metadata.series_name == "primap-hist"
    assert _body(drafted[0])["license"] == "CC-BY-4.0"

    registered: list[httpx.Request] = []
    async with _async(registered, 200, REGISTERED_ONE) as client:
        resource = await client.register_external(
            type="tabular",
            uri="https://example.invalid/data.csv",
        )
    assert resource.tracking_id == UUID(TRACKING_ID)
    assert _body(registered[0])["items"][0]["external_uri"] == "https://example.invalid/data.csv"


def test_the_facade_binds_the_activity_call_to_the_sink() -> None:
    """``bs.activity`` is the sink's own call, so a swapped adapter takes the traffic."""
    recorded: list[httpx.Request] = []

    with _sync(recorded, 201, payloads.BOOK_DETAIL) as client:
        activity = client.activity(kind="build", code_ref="test", config={"a": 1})

    assert activity.kind == "build"
    assert recorded == []


def _parameters(adapter: type, call: str) -> list[tuple[str, Any, Any]]:
    """Name, kind and default of every parameter an adapter's call takes."""
    signature = inspect.signature(getattr(adapter, call))
    return [
        (name, parameter.kind, parameter.default)
        for name, parameter in signature.parameters.items()
    ]


@pytest.mark.parametrize("call", ["activity", "register_external", "draft_book"])
def test_the_live_and_recording_adapters_declare_the_same_call(call: str) -> None:
    """The two adapters substitute for each other, so a caller cannot tell them apart."""
    assert _parameters(LiveSink, call) == _parameters(RecordingSink, call)


@pytest.mark.parametrize("call", ["activity", "register_external", "draft_book"])
def test_the_two_live_adapters_declare_the_same_call(call: str) -> None:
    assert _parameters(LiveSink, call) == _parameters(AsyncLiveSink, call)


def test_a_recording_facade_binds_every_producer_call_to_its_bundle(tmp_path: Path) -> None:
    """A recorded build keeps live reads, so only the three producer calls move to the bundle."""
    bundle = Bundle(tmp_path / "bundle")

    with RecordingBookshelf(bundle) as recording:
        bound = [recording.activity, recording.register_external, recording.draft_book]

    assert [call.__self__ for call in bound] == [recording.recording_sink] * 3
