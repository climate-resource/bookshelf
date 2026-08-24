"""Facade tests for the volume lifecycle and draft cleanup, on both surfaces."""

import json
from typing import Any

import httpx
import pytest

from bookshelf._core.errors import ForbiddenError, ValidationError
from bookshelf.facade import AsyncBookshelf, Bookshelf
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"


def _transport(recorded: list[httpx.Request], status: int, payload: Any) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)  # type: ignore[no-any-return]


def _sync(recorded: list[httpx.Request], status: int, payload: Any = None) -> Bookshelf:
    return Bookshelf(BASE_URL, auth=None, transport=_transport(recorded, status, payload))


def _async(recorded: list[httpx.Request], status: int, payload: Any = None) -> AsyncBookshelf:
    return AsyncBookshelf(
        BASE_URL, auth=None, async_transport=_transport(recorded, status, payload)
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

    with _sync(recorded, 400, refusal) as client, pytest.raises(ValidationError, match="draft"):
        client.discard_draft("b1")


def test_update_draft_patches_the_named_fields() -> None:
    recorded: list[httpx.Request] = []

    with _sync(recorded, 200, payloads.BOOK_RESPONSE) as client:
        updated = client.update_draft("b1", metadata={"note": "corrected units"})

    assert updated.id == "b1"
    assert (recorded[0].method, recorded[0].url.path) == ("PATCH", "/v1/books/b1")
    assert _body(recorded[0]) == {"metadata": {"note": "corrected units"}}


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
