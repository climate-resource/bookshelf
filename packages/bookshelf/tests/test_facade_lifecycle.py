"""Facade tests for the volume lifecycle and draft cleanup, on both surfaces."""

import json
from typing import Any

import httpx
import pytest

from bookshelf._core.errors import ConflictError, ForbiddenError, RequestValidationError
from bookshelf._generated import models
from bookshelf.facade import AsyncBookshelf, Bookshelf
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"


def _transport(recorded: list[httpx.Request], *replies: tuple[int, Any]) -> httpx.MockTransport:
    """Answer each request with the next reply, repeating the last one once the script runs out."""
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        status, payload = queue.pop(0) if len(queue) > 1 else queue[0]
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)  # type: ignore[no-any-return]


def _sync(recorded: list[httpx.Request], status: int, payload: Any = None) -> Bookshelf:
    return Bookshelf(BASE_URL, auth=None, transport=_transport(recorded, (status, payload)))


def _async(recorded: list[httpx.Request], status: int, payload: Any = None) -> AsyncBookshelf:
    return AsyncBookshelf(
        BASE_URL, auth=None, async_transport=_transport(recorded, (status, payload))
    )


def test_create_volume_sends_the_named_fields_only() -> None:
    recorded: list[httpx.Request] = []

    with _sync(recorded, 201, payloads.VOLUME) as client:
        created = client.create_volume(
            "example",
            license="MIT",
            description="Country emissions",
            authors=[{"name": "A Person"}],
        )

    assert created.name == "example"
    request = recorded[0]
    assert (request.method, request.url.path) == ("POST", "/v1/volumes")
    assert _body(request) == {
        "name": "example",
        "discovery": {
            "license": "MIT",
            "description": "Country emissions",
            "authors": [{"name": "A Person"}],
        },
    }


def test_update_volume_omits_the_fields_the_caller_left_alone() -> None:
    """Every field the API takes replaces what is there, so an omitted one must stay off the wire."""
    recorded: list[httpx.Request] = []

    with _sync(recorded, 200, payloads.VOLUME) as client:
        client.update_volume("example", description="Now with units")

    request = recorded[0]
    assert (request.method, request.url.path) == ("PATCH", "/v1/volumes/example")
    assert _body(request) == {"discovery": {"description": "Now with units"}}


def test_delete_volume_reaches_the_api_and_returns_nothing() -> None:
    recorded: list[httpx.Request] = []

    with _sync(recorded, 204) as client:
        assert client.delete_volume("example") is None

    assert (recorded[0].method, recorded[0].url.path) == ("DELETE", "/v1/volumes/example")


def test_delete_volume_surfaces_the_admin_refusal() -> None:
    """Creation needs WRITE and deletion needs ADMIN, so a 403 here is an ordinary outcome."""
    recorded: list[httpx.Request] = []
    refusal = payloads.problem(403, "Forbidden", "admin permission required")

    with _sync(recorded, 403, refusal) as client, pytest.raises(ForbiddenError, match="admin"):
        client.delete_volume("example")


def test_discard_draft_deletes_the_book() -> None:
    recorded: list[httpx.Request] = []

    with _sync(recorded, 204) as client:
        assert client.discard_draft("b1") is None

    assert (recorded[0].method, recorded[0].url.path) == ("DELETE", "/v1/books/b1")


def test_discard_draft_surfaces_the_published_book_refusal() -> None:
    recorded: list[httpx.Request] = []
    refusal = payloads.problem(400, "Cannot delete", "only draft books can be deleted")

    with (
        _sync(recorded, 400, refusal) as client,
        pytest.raises(RequestValidationError, match="draft"),
    ):
        client.discard_draft("b1")


def test_update_draft_patches_the_named_fields() -> None:
    recorded: list[httpx.Request] = []

    with _sync(recorded, 200, payloads.BOOK_RESPONSE) as client:
        updated = client.update_draft("b1", metadata={"note": "corrected units"})

    assert updated.id == "b1"
    assert (recorded[0].method, recorded[0].url.path) == ("PATCH", "/v1/books/b1")
    assert _body(recorded[0]) == {"metadata": {"note": "corrected units"}}


def test_correct_book_replaces_metadata_with_a_reason() -> None:
    recorded: list[httpx.Request] = []
    correction = models.BookCorrection(
        metadata={"maturity": "approved"},
        reason=models.BookCorrectionReason("signed off by science"),
    )

    with _sync(recorded, 200, payloads.BOOK_CORRECTED) as client:
        corrected = client.correct_book(payloads.BOOK_CORRECTED["book_id"], correction)

    assert corrected.corrected == ["metadata"]
    assert corrected.metadata == {"maturity": "approved"}
    assert recorded[0].method == "POST"
    assert recorded[0].url.path == f"/v1/books/{payloads.BOOK_CORRECTED['book_id']}/corrections"
    assert _body(recorded[0]) == {
        "metadata": {"maturity": "approved"},
        "reason": "signed off by science",
    }


def test_correct_book_on_a_draft_is_a_conflict() -> None:
    refusal = payloads.problem(409, "Book is a draft", "edit a draft with PATCH /v1/books/b1")

    with (
        _sync([], 409, refusal) as client,
        pytest.raises(ConflictError, match="draft"),
    ):
        client.correct_book("b1", models.BookCorrection(metadata={}))


def test_correct_book_refuses_a_licence_change() -> None:
    refusal = payloads.problem(422, "Not correctable", "a licence change mints a new edition")
    relicensed = models.BookCorrection(discovery=models.BookDiscoveryInput(license="CC0-1.0"))

    with (
        _sync([], 422, refusal) as client,
        pytest.raises(RequestValidationError, match="licence"),
    ):
        client.correct_book("b1", relicensed)


async def test_async_facade_matches_the_sync_one() -> None:
    created: list[httpx.Request] = []
    async with _async(created, 201, payloads.VOLUME) as client:
        volume = await client.create_volume("example", license="MIT")
    assert volume.name == "example"
    assert _body(created[0]) == {"name": "example", "discovery": {"license": "MIT"}}

    updated: list[httpx.Request] = []
    async with _async(updated, 200, payloads.VOLUME) as client:
        await client.update_volume("example", description="Now with units")
    assert _body(updated[0]) == {"discovery": {"description": "Now with units"}}

    deleted: list[httpx.Request] = []
    async with _async(deleted, 204) as client:
        assert await client.delete_volume("example") is None
        assert await client.discard_draft("b1") is None
    assert [(request.method, request.url.path) for request in deleted] == [
        ("DELETE", "/v1/volumes/example"),
        ("DELETE", "/v1/books/b1"),
    ]

    patched: list[httpx.Request] = []
    async with _async(patched, 200, payloads.BOOK_RESPONSE) as client:
        await client.update_draft("b1", metadata={"note": "fixed"})
    assert _body(patched[0]) == {"metadata": {"note": "fixed"}}

    corrections: list[httpx.Request] = []
    async with _async(corrections, 200, payloads.BOOK_CORRECTED) as client:
        corrected = await client.correct_book(
            "b1", models.BookCorrection(metadata={"maturity": "approved"})
        )
    assert corrected.metadata == {"maturity": "approved"}
    assert (corrections[0].method, corrections[0].url.path) == ("POST", "/v1/books/b1/corrections")


NOT_FOUND = (404, payloads.problem(404, "Not Found", "volume not found"))
CONFLICT = (409, payloads.problem(409, "Conflict", "volume already exists"))
FORBIDDEN = (403, payloads.problem(403, "Forbidden", "no WRITE on this organisation"))
FOUND = (200, payloads.VOLUME_DETAIL)
CREATED = (201, payloads.VOLUME)


GET_OR_CREATE_CASES = [
    pytest.param([FOUND], False, id="present"),
    pytest.param([NOT_FOUND, CREATED, FOUND], True, id="absent"),
    pytest.param([NOT_FOUND, CONFLICT, FOUND], False, id="lost-race"),
]


@pytest.mark.parametrize(("replies", "created"), GET_OR_CREATE_CASES)
def test_get_or_create_volume_reports_whether_it_created(
    replies: list[tuple[int, Any]], created: bool
) -> None:
    recorded: list[httpx.Request] = []
    with Bookshelf(BASE_URL, auth=None, transport=_transport(recorded, *replies)) as client:
        volume, was_created = client.get_or_create_volume("example", license="MIT")

    assert volume.name == "example"
    assert was_created is created
    assert len(recorded) == len(replies)


@pytest.mark.parametrize(("replies", "created"), GET_OR_CREATE_CASES)
async def test_async_get_or_create_volume_matches_the_sync_one(
    replies: list[tuple[int, Any]], created: bool
) -> None:
    recorded: list[httpx.Request] = []
    transport = _transport(recorded, *replies)
    async with AsyncBookshelf(BASE_URL, auth=None, async_transport=transport) as client:
        volume, was_created = await client.get_or_create_volume("example", license="MIT")

    assert volume.name == "example"
    assert was_created is created
    assert len(recorded) == len(replies)


GET_OR_CREATE_FAILURES = [
    pytest.param([NOT_FOUND, FORBIDDEN], ForbiddenError, id="forbidden"),
    pytest.param([NOT_FOUND, CONFLICT, NOT_FOUND], ConflictError, id="hidden"),
]


@pytest.mark.parametrize(("replies", "error"), GET_OR_CREATE_FAILURES)
def test_get_or_create_volume_raises_what_it_cannot_resolve(
    replies: list[tuple[int, Any]], error: type[Exception]
) -> None:
    with (
        Bookshelf(BASE_URL, auth=None, transport=_transport([], *replies)) as client,
        pytest.raises(error),
    ):
        client.get_or_create_volume("example", license="MIT")


@pytest.mark.parametrize(("replies", "error"), GET_OR_CREATE_FAILURES)
async def test_async_get_or_create_volume_raises_what_it_cannot_resolve(
    replies: list[tuple[int, Any]], error: type[Exception]
) -> None:
    transport = _transport([], *replies)
    async with AsyncBookshelf(BASE_URL, auth=None, async_transport=transport) as client:
        with pytest.raises(error):
            await client.get_or_create_volume("example", license="MIT")
