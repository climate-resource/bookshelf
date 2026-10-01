"""How the client behaves when the network, a proxy or the platform fails underneath it."""

from typing import Any

import httpx
import pytest

from bookshelf._core import client as client_module
from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import (
    ConfigurationError,
    GatewayError,
    NotFoundError,
    RateLimitError,
    RequestValidationError,
    ServerError,
    TransportError,
)
from bookshelf._core.retry import RetryPolicy
from bookshelf._generated import models
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"
ATTEMPTS = RetryPolicy().max_attempts

CLOUDFLARE_PAGE = (
    "<!doctype html> <!--[if lt IE 7]> <html class='no-js ie6 oldie' lang='en-US'> <![endif]-->"
    "<title>Access denied | bookshelf.test used Cloudflare to restrict access</title>"
)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record every backoff instead of waiting it out."""
    recorded: list[float] = []

    async def record_async(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(client_module.time, "sleep", recorded.append)
    monkeypatch.setattr(client_module.asyncio, "sleep", record_async)
    return recorded


def make_client(handler: Any) -> BookshelfClient:
    return BookshelfClient(
        BASE_URL,
        auth=None,
        transport=httpx.MockTransport(handler),
        async_transport=httpx.MockTransport(handler),
    )


def counting(respond: Any) -> tuple[dict[str, int], Any]:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return respond(request, calls["count"])

    return calls, handler


def html(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        text=CLOUDFLARE_PAGE,
        headers={"content-type": "text/html; charset=UTF-8", **(headers or {})},
    )


def test_a_rate_limited_read_waits_out_retry_after(sleeps: list[float]) -> None:
    calls, handler = counting(
        lambda _request, n: (
            html(429, {"retry-after": "2"})
            if n == 1
            else httpx.Response(200, json=payloads.BOOK_LIST)
        )
    )

    with make_client(handler) as client:
        client.list_books()

    assert calls["count"] == 2
    assert len(sleeps) == 1
    assert 2.0 <= sleeps[0] <= 2.0 + RetryPolicy().backoff_base


def test_a_rate_limited_write_is_replayed(sleeps: list[float]) -> None:
    """A 429 is refused before the API handles it, so replaying cannot duplicate the write."""
    calls, handler = counting(
        lambda _request, n: (
            html(429, {"retry-after": "1"})
            if n == 1
            else httpx.Response(200, json=payloads.REGISTERED)
        )
    )

    with make_client(handler) as client:
        client.register_resources(models.RegisterResourcesRequest(items=[]))

    assert calls["count"] == 2


async def test_exhausted_rate_limit_raises_a_typed_error(sleeps: list[float]) -> None:
    calls, handler = counting(lambda _request, _n: html(429, {"retry-after": "3"}))

    async with make_client(handler) as client:
        with pytest.raises(RateLimitError) as excinfo:
            await client.list_books_async()

    assert calls["count"] == ATTEMPTS
    assert excinfo.value.status_code == 429
    assert excinfo.value.retry_after == 3.0
    assert "<" not in str(excinfo.value)


def test_a_retry_after_beyond_the_ceiling_fails_at_once(sleeps: list[float]) -> None:
    calls, handler = counting(lambda _request, _n: html(429, {"retry-after": "3600"}))

    with make_client(handler) as client, pytest.raises(RateLimitError) as excinfo:
        client.list_books()

    assert calls["count"] == 1
    assert sleeps == []
    assert excinfo.value.retry_after == 3600.0


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_data_read_is_never_replayed_after_a_gateway_error(
    sleeps: list[float], status: int
) -> None:
    """A replayed heavy read lands on a fresh pod and can take that one down too."""
    calls, handler = counting(lambda _request, _n: html(status))

    with make_client(handler) as client, pytest.raises(ServerError):
        client.get_book_resource_preview("b1", "data", limit=5)

    assert calls["count"] == 1


def test_a_data_read_is_never_replayed_after_a_read_timeout(sleeps: list[float]) -> None:
    def respond(request: httpx.Request, _n: int) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    calls, handler = counting(respond)

    with make_client(handler) as client, pytest.raises(TransportError):
        client.query_resource_data("r1")

    assert calls["count"] == 1


def test_a_metadata_read_backs_off_before_replaying_a_gateway_error(sleeps: list[float]) -> None:
    calls, handler = counting(
        lambda _request, n: html(502) if n == 1 else httpx.Response(200, json=payloads.BOOK_LIST)
    )

    with make_client(handler) as client:
        client.list_books()

    assert calls["count"] == 2
    assert sleeps and sleeps[0] >= RetryPolicy().backoff_base / 2


def test_an_application_500_is_not_replayed(sleeps: list[float]) -> None:
    """A 500 is the API failing on this request, so the same request fails the same way."""
    calls, handler = counting(
        lambda _request, _n: httpx.Response(
            500,
            json=payloads.problem(500, "Internal Server Error", "boom"),
            headers={"content-type": "application/problem+json"},
        )
    )

    with make_client(handler) as client, pytest.raises(ServerError):
        client.list_books()

    assert calls["count"] == 1


def test_an_html_error_page_never_reaches_the_message(sleeps: list[float]) -> None:
    calls, handler = counting(lambda _request, _n: html(502))

    with make_client(handler) as client, pytest.raises(ServerError) as excinfo:
        client.get_book("b1")

    message = str(excinfo.value)
    assert "<" not in message
    assert "502" in excinfo.value.detail
    assert f"{BASE_URL}/v1/books/b1" in message


def test_a_non_json_4xx_is_a_gateway_error(sleeps: list[float]) -> None:
    calls, handler = counting(lambda _request, _n: html(403))

    with make_client(handler) as client, pytest.raises(GatewayError) as excinfo:
        client.list_books()

    assert calls["count"] == 1
    assert excinfo.value.status_code == 403
    assert "403" in excinfo.value.detail
    assert "<" not in str(excinfo.value)


def test_the_reported_url_drops_the_query_string(sleeps: list[float]) -> None:
    """A presigned URL carries its signature in the query, so it must not reach a log."""
    calls, handler = counting(lambda _request, _n: html(403))

    with make_client(handler) as client, pytest.raises(GatewayError) as excinfo:
        client.get_url("https://store.test/object?X-Amz-Signature=secret")

    assert "secret" not in str(excinfo.value)
    assert "https://store.test/object" in str(excinfo.value)


def test_a_validation_failure_names_the_fields(sleeps: list[float]) -> None:
    problem = dict(
        payloads.problem(422, "Unprocessable Entity", "Request validation failed"),
        errors=[
            {
                "type": "enum",
                "loc": ["query", "type"],
                "msg": "Input should be 'volume' or 'book'",
                "input": "nonsense",
            }
        ],
    )
    calls, handler = counting(
        lambda _request, _n: httpx.Response(
            422, json=problem, headers={"content-type": "application/problem+json"}
        )
    )

    with make_client(handler) as client, pytest.raises(RequestValidationError) as excinfo:
        client.list_books()

    assert excinfo.value.detail == (
        "Request validation failed: query.type: Input should be 'volume' or 'book'"
    )


@pytest.mark.parametrize("name", [".", ".."])
def test_a_dot_segment_cannot_reshape_the_path(sleeps: list[float], name: str) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(
            404,
            json=payloads.problem(404, "Not Found", "no such volume"),
            headers={"content-type": "application/problem+json"},
        )

    with make_client(handler) as client, pytest.raises(NotFoundError):
        client.get_volume(name)

    assert seen == ["/v1/volumes/" + "%2E" * len(name)]


def test_a_connection_failure_names_the_url(sleeps: list[float]) -> None:
    def respond(request: httpx.Request, _n: int) -> httpx.Response:
        raise httpx.ConnectError("[Errno 8] nodename nor servname provided", request=request)

    calls, handler = counting(respond)

    with make_client(handler) as client, pytest.raises(TransportError) as excinfo:
        client.list_books()

    assert f"{BASE_URL}/v1/books" in str(excinfo.value)
    assert calls["count"] == ATTEMPTS


async def test_a_connect_timeout_is_not_replayed(sleeps: list[float]) -> None:
    """Each attempt already waited the whole connect timeout on an unreachable host."""

    def respond(request: httpx.Request, _n: int) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    calls, handler = counting(respond)

    async with make_client(handler) as client:
        with pytest.raises(TransportError) as excinfo:
            await client.list_books_async()

    assert calls["count"] == 1
    assert f"{BASE_URL}/v1/books" in str(excinfo.value)
    assert "timed out" in str(excinfo.value)


def test_connecting_has_a_shorter_timeout_than_reading() -> None:
    with make_client(lambda _request: httpx.Response(200)) as client:
        timeout = client._sync_client.timeout

    assert timeout.read == 30.0
    assert timeout.connect is not None and timeout.connect < timeout.read


def test_a_streamed_download_failure_names_the_url(tmp_path: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with make_client(handler) as client, pytest.raises(TransportError) as excinfo:
        client.stream_url_to_path("https://store.test/object?sig=secret", tmp_path / "out")

    assert "https://store.test/object" in str(excinfo.value)
    assert "secret" not in str(excinfo.value)


@pytest.mark.parametrize("url", ["not-a-url", "ftp://x", "https://"])
def test_a_malformed_base_url_is_a_configuration_error(url: str) -> None:
    with pytest.raises(ConfigurationError, match="BOOKSHELF_URL"):
        BookshelfClient(url, auth=None)
