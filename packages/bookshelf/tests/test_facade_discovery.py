"""Facade tests for catalogue discovery, on both surfaces."""

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from bookshelf.facade import AsyncBookshelf, Bookshelf
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"


def _volume_list(names: list[str], *, has_more: bool = False) -> dict[str, Any]:
    return {
        "items": [dict(payloads.VOLUME, id=f"vol_{name}", name=name) for name in names],
        "total": len(names),
        "limit": 50,
        "offset": 0,
        "has_more": has_more,
    }


def _transport(recorded: list[httpx.Request], pages: list[Any]) -> httpx.MockTransport:
    """Serve one payload per request, so a paging caller sees the pages in order."""
    remaining = list(pages)

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json=remaining.pop(0))

    return httpx.MockTransport(handler)


def _sync(recorded: list[httpx.Request], pages: list[Any]) -> Bookshelf:
    return Bookshelf(BASE_URL, auth=None, transport=_transport(recorded, pages))


def _async(recorded: list[httpx.Request], pages: list[Any]) -> AsyncBookshelf:
    return AsyncBookshelf(BASE_URL, auth=None, async_transport=_transport(recorded, pages))


def _query(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.url.query.decode())


def test_search_volumes_sends_the_named_filters_only() -> None:
    recorded: list[httpx.Request] = []

    with _sync(recorded, [_volume_list(["ceds"])]) as client:
        found = client.search_volumes("emissions", topic=["climate"], license="CC-BY-4.0")

    assert [volume.name for volume in found.items] == ["ceds"]
    query = _query(recorded[0])
    assert query["q"] == ["emissions"]
    assert query["topic"] == ["climate"]
    assert query["license"] == ["CC-BY-4.0"]
    # An omitted filter must stay off the wire rather than arrive empty.
    assert "publisher" not in query
    assert "deprecated" not in query


def test_search_volumes_with_no_arguments_lists_the_catalogue() -> None:
    recorded: list[httpx.Request] = []

    with _sync(recorded, [_volume_list(["a", "b"])]) as client:
        found = client.search_volumes()

    assert [volume.name for volume in found.items] == ["a", "b"]
    assert _query(recorded[0]) == {}


@pytest.mark.asyncio
async def test_async_search_volumes_matches_the_sync_surface() -> None:
    recorded: list[httpx.Request] = []

    async with _async(recorded, [_volume_list(["ceds"])]) as client:
        found = await client.search_volumes("emissions")

    assert [volume.name for volume in found.items] == ["ceds"]
    assert _query(recorded[0])["q"] == ["emissions"]
