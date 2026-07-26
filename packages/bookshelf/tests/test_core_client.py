"""Wiring smokes for the unified client: both shells route through the same build/parse core."""

import json
from typing import Any

import httpx
import pytest

from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import NotFoundError, ServerError, TransportError
from bookshelf._core.retry import RetryPolicy
from bookshelf._generated import models
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"
NO_RETRY = RetryPolicy(max_attempts=1)
FAST_RETRY = RetryPolicy(max_attempts=3, backoff_base=0.0, backoff_cap=0.0)


def make_client(handler: Any, *, retry: RetryPolicy = NO_RETRY, **kwargs: Any) -> BookshelfClient:
    return BookshelfClient(
        BASE_URL,
        retry=retry,
        transport=httpx.MockTransport(handler),
        async_transport=httpx.MockTransport(handler),
        **kwargs,
    )


def api_handler(request: httpx.Request) -> httpx.Response:
    routes: dict[tuple[str, str], tuple[int, Any]] = {
        ("POST", "/v1/resources/registrations"): (200, payloads.REGISTERED),
        ("POST", "/v1/books"): (201, payloads.BOOK_DETAIL),
        ("GET", "/v1/books"): (200, payloads.BOOK_LIST),
        ("POST", "/v1/books/b1/publish"): (200, payloads.BOOK_DETAIL),
        ("GET", "/v1/resources"): (200, payloads.RESOURCE_LIST),
    }
    entry = routes.get((request.method, request.url.path))
    if entry is None:
        return httpx.Response(404, json={"detail": "no such route in fixture"})
    status, payload = entry
    return httpx.Response(status, json=payload)


def test_sync_shell_round_trips_registrations() -> None:
    with make_client(api_handler) as client:
        response = client.register_resources(models.RegisterResourcesRequest(items=[]))
    assert isinstance(response, models.RegisterResourcesResponse)
    assert response.atomic is True


def test_lazy_per_surface_transports() -> None:
    client = make_client(api_handler)
    assert client._sync is None and client._async is None
    client.list_books()
    assert client._sync is not None and client._async is None
    client.close()


def test_bearer_auth_reaches_the_api() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=payloads.BOOK_LIST)

    class Bearer(httpx.Auth):
        def auth_flow(self, request: httpx.Request) -> Any:
            request.headers["authorization"] = "Bearer bsat_test"
            yield request

    with make_client(handler, auth=Bearer()) as client:
        client.list_books()
    assert seen["authorization"] == "Bearer bsat_test"


def test_presigned_put_never_forwards_the_api_credential() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        seen["content"] = request.content
        return httpx.Response(200, headers={"etag": '"p1"'})

    class Bearer(httpx.Auth):
        def auth_flow(self, request: httpx.Request) -> Any:
            request.headers["authorization"] = "Bearer bsat_test"
            yield request

    with make_client(handler, auth=Bearer()) as client:
        etag = client.put_presigned("https://s3.test/part1?sig=abc", b"bytes")
    assert etag == '"p1"'
    assert seen["url"] == "https://s3.test/part1?sig=abc"
    assert seen["content"] == b"bytes"
    assert seen["authorization"] is None


def test_transient_5xx_is_retried_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=payloads.BOOK_LIST)

    with make_client(handler, retry=FAST_RETRY) as client:
        response = client.list_books()
    assert calls["count"] == 3
    assert response.total == 0


def test_5xx_after_exhausted_retries_raises_server_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, text="boom")

    with make_client(handler, retry=FAST_RETRY) as client, pytest.raises(ServerError):
        client.list_books()
    assert calls["count"] == 3


async def test_network_failure_retries_then_raises_transport_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectError("connection refused")

    async with make_client(handler, retry=FAST_RETRY) as client:
        with pytest.raises(TransportError):
            await client.list_books_async()
    assert calls["count"] == 3


def test_4xx_is_never_retried() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            404,
            json=dict(payloads.PROBLEM_CONFLICT, status=404, title="Not Found", detail="gone"),
            headers={"content-type": "application/problem+json"},
        )

    with (
        make_client(handler, retry=FAST_RETRY) as client,
        pytest.raises(NotFoundError, match="gone"),
    ):
        client.get_book("b1")
    assert calls["count"] == 1


def test_upload_initiate_dedupe_short_circuit_reaches_the_shell() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["hash"].startswith("sha256:")
        return httpx.Response(200, json=payloads.UPLOAD_EXISTS)

    with make_client(handler) as client:
        response = client.initiate_ingest_upload(
            models.IngestUploadInitiateRequest(hash="sha256:" + "0" * 64, size_bytes=10)
        )
    assert isinstance(response, models.UploadAlreadyExistsResponse)
