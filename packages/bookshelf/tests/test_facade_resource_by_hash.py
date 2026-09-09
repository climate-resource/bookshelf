"""Tests for resolving a content digest into the one resource an organisation holds for it."""

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from bookshelf._core.errors import BookshelfError, NotFoundError
from bookshelf.facade import AsyncBookshelf, Bookshelf
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"
DIGEST = "sha256:" + "0" * 64


def _transport(recorded: list[httpx.Request], items: list[Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"items": items})

    return httpx.MockTransport(handler)


def test_resource_by_hash_asks_for_the_canonical_merging_row() -> None:
    recorded: list[httpx.Request] = []

    with Bookshelf(
        BASE_URL, auth=None, transport=_transport(recorded, [payloads.RESOURCE_READ])
    ) as client:
        resource = client.resource_by_hash(DIGEST)

    assert str(resource.tracking_id) == payloads.RESOURCE_READ["tracking_id"]
    assert resource.metadata.hash == DIGEST
    request = recorded[0]
    assert (request.method, request.url.path) == ("GET", "/v1/resources")
    assert parse_qs(request.url.query.decode()) == {
        "hash": [DIGEST],
        "dedupe": ["true"],
        "limit": ["2"],
    }


def test_resource_by_hash_names_the_missing_digest() -> None:
    with (
        Bookshelf(BASE_URL, auth=None, transport=_transport([], [])) as client,
        pytest.raises(NotFoundError, match=f"no resource with hash {DIGEST}"),
    ):
        client.resource_by_hash(DIGEST)


def test_resource_by_hash_refuses_an_ambiguous_answer() -> None:
    """The platform promises one merging row per digest, so two is a fault worth surfacing."""
    two = [payloads.RESOURCE_READ, payloads.RESOURCE_READ]

    with (
        Bookshelf(BASE_URL, auth=None, transport=_transport([], two)) as client,
        pytest.raises(BookshelfError, match="resolves to 2 merging resources"),
    ):
        client.resource_by_hash(DIGEST)


async def test_resource_by_hash_has_an_async_twin() -> None:
    recorded: list[httpx.Request] = []

    async with AsyncBookshelf(
        BASE_URL, auth=None, async_transport=_transport(recorded, [payloads.RESOURCE_READ])
    ) as client:
        resource = await client.resource_by_hash(DIGEST)

    assert str(resource.tracking_id) == payloads.RESOURCE_READ["tracking_id"]
    assert parse_qs(recorded[0].url.query.decode())["dedupe"] == ["true"]
