"""Tests for resolving a content digest into the one resource an organisation holds for it."""

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from bookshelf._core.errors import BookshelfError, NotFoundError
from bookshelf._facade import Bookshelf
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
    assert resource.content_hash() == DIGEST
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


@pytest.mark.parametrize(
    "content_hash", ["sha256:abc", "md5:" + "0" * 32, "0" * 64, "sha256:" + "g" * 64, ""]
)
def test_resource_by_hash_refuses_a_malformed_digest_before_asking(content_hash: str) -> None:
    recorded: list[httpx.Request] = []

    with (
        Bookshelf(BASE_URL, auth=None, transport=_transport(recorded, [])) as client,
        pytest.raises(ValueError, match="sha256"),
    ):
        client.resource_by_hash(content_hash)

    assert recorded == []


def test_resource_by_hash_asks_for_upper_case_hex_in_lower_case() -> None:
    """The platform stores digests in lower case, so an upper case one would never match."""
    digest = "sha256:" + "ab" * 32
    recorded: list[httpx.Request] = []

    with Bookshelf(
        BASE_URL, auth=None, transport=_transport(recorded, [payloads.RESOURCE_READ])
    ) as client:
        client.resource_by_hash("sha256:" + "AB" * 32)
        client.resource_by_hash("sha256:" + "Ab" * 32)

    assert [parse_qs(request.url.query.decode())["hash"] for request in recorded] == [
        [digest],
        [digest],
    ]
