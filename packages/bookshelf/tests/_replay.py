"""A mocked deployment answering the two calls a bundle replay makes, shared across modules."""

import json
from typing import Any

import httpx

from bookshelf.facade import Bookshelf
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"


def replay_response(
    *,
    converged: bool = False,
    resource_count: int = 1,
    dedupe_hits: int = 0,
    edition: int = 1,
    book: bool = True,
    statuses: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One replay response body, framed as the deployment would answer this bundle.

    ``statuses`` maps a bundle-local name to what the replay wrote for it.
    """
    return {
        "book": (
            {**payloads.BOOK_DETAIL, "status": "published", "edition": edition} if book else None
        ),
        "resources": [
            {"name": name, "tracking_id": None, "status": status}
            for name, status in (statuses or {}).items()
        ],
        "dedupe_hits": dedupe_hits,
        "resource_count": resource_count,
        "converged": converged,
    }


def replay_client(
    recorded: list[httpx.Request],
    *,
    response: dict[str, Any] | None = None,
) -> Bookshelf:
    """A client whose deployment holds every upload already and answers one replay."""
    payload = replay_response() if response is None else response

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        path = request.url.path
        if path == "/v1/resources/uploads":
            return httpx.Response(200, json=payloads.UPLOAD_EXISTS)
        if path == "/v1/bundles/replay":
            return httpx.Response(200, json=payload)
        raise AssertionError(f"unexpected request to {path}")

    return Bookshelf(BASE_URL, auth=None, transport=httpx.MockTransport(handler))


def replayed(recorded: list[httpx.Request]) -> dict[str, Any]:
    """The one replay request body the client sent."""
    sent = [request for request in recorded if request.url.path == "/v1/bundles/replay"]
    assert len(sent) == 1, f"expected one replay, got {len(sent)}"
    body: dict[str, Any] = json.loads(sent[0].content)
    return body
