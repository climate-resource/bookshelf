"""Wiring smokes for the unified client: both shells route through the same build/parse core."""

import json
from typing import Any

import httpx
import pytest

from bookshelf._core import client as client_module
from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import NotFoundError, ServerError, TransportError
from bookshelf._core.retry import RetryPolicy
from bookshelf._generated import models
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"
ATTEMPTS = RetryPolicy().max_attempts


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the retry backoff out of the wall clock."""

    async def no_async_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(client_module.asyncio, "sleep", no_async_sleep)


def make_client(handler: Any, **kwargs: Any) -> BookshelfClient:
    return BookshelfClient(
        BASE_URL,
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


def _recording_handler(seen: list[tuple[str, str]], status: int, payload: Any) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=payload)

    return handler


def test_volume_lifecycle_round_trips_on_both_shells() -> None:
    seen: list[tuple[str, str]] = []
    handler = _recording_handler(seen, 201, payloads.VOLUME)

    with make_client(handler) as client:
        created = client.create_volume(
            models.VolumeCreate(
                name="example", discovery=models.VolumeDiscoveryInput(license="MIT")
            )
        )
    assert created.name == "example"
    assert seen == [("POST", "/v1/volumes")]


async def test_volume_lifecycle_round_trips_on_the_async_shell() -> None:
    seen: list[tuple[str, str]] = []
    handler = _recording_handler(seen, 200, payloads.VOLUME)

    async with make_client(handler) as client:
        updated = await client.update_volume_async(
            "example",
            models.VolumeUpdate(discovery=models.VolumeDiscoveryInput(description="units fixed")),
        )
    assert updated.name == "example"
    assert seen == [("PATCH", "/v1/volumes/example")]


def test_deletions_return_nothing_on_both_shells() -> None:
    seen: list[tuple[str, str]] = []
    handler = _recording_handler(seen, 204, None)

    with make_client(handler) as client:
        assert client.delete_volume("example") is None
        assert client.delete_book("b1") is None
    assert seen == [("DELETE", "/v1/volumes/example"), ("DELETE", "/v1/books/b1")]


async def test_async_deletions_return_nothing() -> None:
    seen: list[tuple[str, str]] = []
    handler = _recording_handler(seen, 204, None)

    async with make_client(handler) as client:
        assert await client.delete_volume_async("example") is None
        assert await client.delete_book_async("b1") is None
    assert seen == [("DELETE", "/v1/volumes/example"), ("DELETE", "/v1/books/b1")]


def test_update_book_patches_the_draft() -> None:
    seen: list[tuple[str, str]] = []
    handler = _recording_handler(seen, 200, payloads.BOOK_RESPONSE)

    with make_client(handler) as client:
        updated = client.update_book("b1", models.BookUpdate(metadata={"note": "fixed"}))
    assert updated.id == "b1"
    assert seen == [("PATCH", "/v1/books/b1")]


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
        if calls["count"] < ATTEMPTS:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=payloads.BOOK_LIST)

    with make_client(handler) as client:
        response = client.list_books()
    assert calls["count"] == ATTEMPTS
    assert response.total == 0


def test_5xx_after_exhausted_retries_raises_server_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, text="boom")

    with make_client(handler) as client, pytest.raises(ServerError):
        client.list_books()
    assert calls["count"] == ATTEMPTS


def test_a_write_is_not_replayed_after_a_5xx() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(502, text="bad gateway")

    with make_client(handler) as client, pytest.raises(ServerError):
        client.register_resources(models.RegisterResourcesRequest(items=[]))
    assert calls["count"] == 1


async def test_a_write_is_not_replayed_after_a_5xx_async() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(504, text="gateway timeout")

    async with make_client(handler) as client:
        with pytest.raises(ServerError):
            await client.publish_book_async("b1")
    assert calls["count"] == 1


def test_a_write_is_not_replayed_after_a_read_timeout() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ReadTimeout("timed out waiting for the response")

    with make_client(handler) as client, pytest.raises(TransportError):
        client.register_resources(models.RegisterResourcesRequest(items=[]))
    assert calls["count"] == 1


def test_a_write_is_retried_when_the_connection_never_came_up() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < ATTEMPTS:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json=payloads.REGISTERED)

    with make_client(handler) as client:
        response = client.register_resources(models.RegisterResourcesRequest(items=[]))
    assert calls["count"] == ATTEMPTS
    assert response.atomic is True


def test_presigned_put_is_still_retried() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < ATTEMPTS:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, headers={"etag": '"p1"'})

    with make_client(handler) as client:
        etag = client.put_presigned("https://s3.test/part1?sig=abc", b"bytes")
    assert calls["count"] == ATTEMPTS
    assert etag == '"p1"'


def test_permanent_5xx_is_not_retried() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(501, text="not implemented")

    with make_client(handler) as client, pytest.raises(ServerError):
        client.list_books()
    assert calls["count"] == 1


async def test_network_failure_retries_then_raises_transport_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectError("connection refused")

    async with make_client(handler) as client:
        with pytest.raises(TransportError):
            await client.list_books_async()
    assert calls["count"] == ATTEMPTS


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
        make_client(handler) as client,
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
