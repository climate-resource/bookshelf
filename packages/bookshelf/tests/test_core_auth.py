"""Behavioural tests for the credential providers.

Every provider is exercised through real httpx clients over MockTransport,
so the sans-io flow, the refresh yields, and the locking are all covered on both surfaces.
"""

import asyncio
import json
import time
import warnings
from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pytest

from bookshelf._core.auth import (
    REFRESH_LEEWAY,
    AnonymousFallback,
    BsatAssertion,
    ClientCredentials,
    RefreshTokenExchange,
    StaticToken,
    decode_jwt_expiry,
)
from bookshelf._core.errors import AuthenticationError

TOKEN_URL = "https://issuer.test/oauth2/token"
API_URL = "https://bookshelf.test/v1/books"


def jwt_with_exp(exp: float) -> str:
    payload = urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"h.{payload}.s"


class TokenIssuer:
    """A MockTransport handler pairing a token endpoint with a bearer-checking API."""

    def __init__(
        self,
        *,
        expires_in: int | None = 3600,
        rotate_refresh: bool = False,
        token_status: int = 200,
        access_token: str | None = None,
        token_delay: float = 0.0,
    ) -> None:
        self.token_requests: list[dict[str, str]] = []
        self.api_tokens: list[str] = []
        self.minted = 0
        self._expires_in = expires_in
        self._rotate_refresh = rotate_refresh
        self._token_status = token_status
        self._access_token = access_token
        self._token_delay = token_delay
        self.rejected_tokens: set[str] = set()

    def _token_response(self, request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        self.token_requests.append(form)
        if self._token_status != 200:
            return httpx.Response(
                self._token_status, json={"error": "invalid_grant", "error_description": "nope"}
            )
        self.minted += 1
        payload: dict[str, Any] = {
            "access_token": self._access_token or f"tok-{self.minted}",
            "token_type": "Bearer",
        }
        if self._expires_in is not None:
            payload["expires_in"] = self._expires_in
        if self._rotate_refresh:
            payload["refresh_token"] = f"rt-{self.minted}"
        return httpx.Response(200, json=payload)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            if self._token_delay:
                time.sleep(self._token_delay)
            return self._token_response(request)
        bearer = request.headers.get("authorization", "")
        token = bearer.removeprefix("Bearer ")
        self.api_tokens.append(token)
        if token in self.rejected_tokens:
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json={"ok": True})

    async def async_call(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL and self._token_delay:
            await asyncio.sleep(self._token_delay)
            return self._token_response(request)
        return self(request)


def sync_client(issuer: TokenIssuer, auth: httpx.Auth) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(issuer), auth=auth)


def async_client(issuer: TokenIssuer, auth: httpx.Auth) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(issuer.async_call), auth=auth)


def test_decode_jwt_expiry_reads_exp_claim() -> None:
    assert decode_jwt_expiry(jwt_with_exp(1234.0)) == 1234.0
    assert decode_jwt_expiry("not-a-jwt") is None
    assert decode_jwt_expiry("a.!!!.c") is None


def test_static_token_sets_bearer_header_on_both_surfaces() -> None:
    issuer = TokenIssuer()
    auth = StaticToken("bsat_fixed")
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
    assert issuer.api_tokens == ["bsat_fixed"]


async def test_static_token_async_surface() -> None:
    issuer = TokenIssuer()
    async with async_client(issuer, StaticToken("bsat_fixed")) as client:
        await client.get(API_URL)
    assert issuer.api_tokens == ["bsat_fixed"]


def test_static_token_does_not_replay_on_401() -> None:
    issuer = TokenIssuer()
    issuer.rejected_tokens.add("bsat_fixed")
    with sync_client(issuer, StaticToken("bsat_fixed")) as client:
        response = client.get(API_URL)
    assert response.status_code == 401
    assert issuer.api_tokens == ["bsat_fixed"]


def test_client_credentials_mints_then_caches() -> None:
    issuer = TokenIssuer()
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
        client.get(API_URL)
    assert issuer.minted == 1
    assert issuer.api_tokens == ["tok-1", "tok-1"]
    assert issuer.token_requests[0]["grant_type"] == "client_credentials"
    assert issuer.token_requests[0]["client_id"] == "cid"
    assert issuer.token_requests[0]["client_secret"] == "secret"


def test_proactive_refresh_inside_leeway_window() -> None:
    issuer = TokenIssuer(expires_in=int(REFRESH_LEEWAY) - 60)
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
        client.get(API_URL)
    # Every token expires inside the leeway window, so each request re-mints.
    assert issuer.minted == 2


def test_401_refreshes_once_and_replays_once() -> None:
    issuer = TokenIssuer()
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
        issuer.rejected_tokens.add("tok-1")
        response = client.get(API_URL)
    assert response.status_code == 200
    assert issuer.minted == 2
    assert issuer.api_tokens == ["tok-1", "tok-1", "tok-2"]


def test_second_401_raises_authentication_error() -> None:
    issuer = TokenIssuer()
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
        issuer.rejected_tokens.update({"tok-1", "tok-2"})
        with pytest.raises(AuthenticationError):
            client.get(API_URL)


async def test_second_401_raises_authentication_error_async() -> None:
    issuer = TokenIssuer()
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    async with async_client(issuer, auth) as client:
        await client.get(API_URL)
        issuer.rejected_tokens.update({"tok-1", "tok-2"})
        with pytest.raises(AuthenticationError):
            await client.get(API_URL)


def test_refresh_failure_raises_authentication_error() -> None:
    issuer = TokenIssuer(token_status=400)
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    with sync_client(issuer, auth) as client, pytest.raises(AuthenticationError) as excinfo:
        client.get(API_URL)
    assert "nope" in str(excinfo.value)


def test_expiry_falls_back_to_jwt_exp_claim() -> None:
    fresh = jwt_with_exp(time.time() + 10_000)
    issuer = TokenIssuer(expires_in=None, access_token=fresh)
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
        client.get(API_URL)
    assert issuer.minted == 1


def test_single_flight_refresh_across_threads() -> None:
    issuer = TokenIssuer(token_delay=0.05)
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    with sync_client(issuer, auth) as client, ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: client.get(API_URL), range(5)))
    assert all(r.status_code == 200 for r in responses)
    assert issuer.minted == 1


async def test_single_flight_refresh_across_coroutines() -> None:
    issuer = TokenIssuer(token_delay=0.05)
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    async with async_client(issuer, auth) as client:
        responses = await asyncio.gather(*(client.get(API_URL) for _ in range(5)))
    assert all(r.status_code == 200 for r in responses)
    assert issuer.minted == 1


def test_one_provider_serves_both_surfaces() -> None:
    issuer = TokenIssuer()
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)

    async def use_async() -> None:
        async with async_client(issuer, auth) as client:
            await client.get(API_URL)

    with sync_client(issuer, auth) as client:
        client.get(API_URL)
    asyncio.run(use_async())
    assert issuer.minted == 1
    assert issuer.api_tokens == ["tok-1", "tok-1"]


def test_refresh_token_exchange_sends_refresh_grant() -> None:
    issuer = TokenIssuer(rotate_refresh=True)
    auth = RefreshTokenExchange(
        access_token=None,
        refresh_token="rt-0",
        token_url=TOKEN_URL,
        client_id="cid",
    )
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
    form = issuer.token_requests[0]
    assert form["grant_type"] == "refresh_token"
    assert form["refresh_token"] == "rt-0"
    assert form["client_id"] == "cid"


def test_refresh_token_rotation_is_used_and_persisted() -> None:
    issuer = TokenIssuer(rotate_refresh=True, expires_in=int(REFRESH_LEEWAY) - 60)
    rotations: list[tuple[str, str | None]] = []
    auth = RefreshTokenExchange(
        access_token=None,
        refresh_token="rt-0",
        token_url=TOKEN_URL,
        client_id="cid",
        on_rotate=lambda access, refresh, _expires_at: rotations.append((access, refresh)),
    )
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
        client.get(API_URL)
    assert [form["refresh_token"] for form in issuer.token_requests] == ["rt-0", "rt-1"]
    assert rotations == [("tok-1", "rt-1"), ("tok-2", "rt-2")]


def test_refresh_token_exchange_keeps_valid_access_token() -> None:
    issuer = TokenIssuer()
    auth = RefreshTokenExchange(
        access_token="still-good",
        refresh_token="rt-0",
        token_url=TOKEN_URL,
        client_id="cid",
        expires_at=time.time() + 10_000,
    )
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
    assert issuer.minted == 0
    assert issuer.api_tokens == ["still-good"]


def test_bsat_assertion_sends_jwt_bearer_grant_and_rotates_assertion() -> None:
    class BsatIssuer(TokenIssuer):
        def _token_response(self, request: httpx.Request) -> httpx.Response:
            response = super()._token_response(request)
            payload = json.loads(response.content)
            payload["identity_assertion"] = f"bsia-{self.minted}"
            return httpx.Response(200, json=payload)

    issuer = BsatIssuer(expires_in=int(REFRESH_LEEWAY) - 60)
    auth = BsatAssertion("bsia-0", token_url=TOKEN_URL)
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
        client.get(API_URL)
    grants = [form["grant_type"] for form in issuer.token_requests]
    assert grants == ["urn:ietf:params:oauth:grant-type:jwt-bearer"] * 2
    assert [form["assertion"] for form in issuer.token_requests] == ["bsia-0", "bsia-1"]


def test_handed_in_token_of_unknown_expiry_is_refreshed_before_use() -> None:
    """A stored token with no known expiry may already be dead server-side."""
    issuer = TokenIssuer()
    auth = RefreshTokenExchange(
        access_token="maybe-dead",
        refresh_token="rt-0",
        token_url=TOKEN_URL,
        client_id="cid",
    )
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
    assert issuer.minted == 1
    assert issuer.api_tokens == ["tok-1"]


def test_minted_token_of_unknown_expiry_is_not_refreshed_every_request() -> None:
    """A token this provider just minted is trusted until a 401 says otherwise."""
    issuer = TokenIssuer(expires_in=None, access_token="opaque-no-exp")
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
        client.get(API_URL)
    assert issuer.minted == 1


def test_bsat_assertion_derives_token_url_from_base_url() -> None:
    auth = BsatAssertion("bsia-0", base_url="https://bookshelf.test/")
    assert auth._token_url == "https://bookshelf.test/oauth2/token"
    with pytest.raises(ValueError, match="exactly one"):
        BsatAssertion("bsia-0")


def test_streaming_response_body_is_not_buffered() -> None:
    """Only the token response is read, so streamed downloads stay streamed."""
    issuer = TokenIssuer()
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    # requires_response_body would make httpx buffer every API response,
    # not just tokens.
    assert auth.requires_response_body is False
    with sync_client(issuer, auth) as client, client.stream("GET", API_URL) as response:
        assert json.loads(response.read()) == {"ok": True}
    assert issuer.minted == 1


def test_locks_are_not_held_across_api_calls() -> None:
    """The refresh lock must only guard the token exchange, never the API request itself."""
    issuer = TokenIssuer()
    auth = ClientCredentials("cid", "secret", token_url=TOKEN_URL)
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
    assert not auth._sync_lock.locked()
    assert not auth._async_lock.locked()


def fallback(inner: httpx.Auth) -> AnonymousFallback:
    return AnonymousFallback(inner, message="Falling back.")


def test_anonymous_fallback_passes_a_working_credential_through() -> None:
    issuer = TokenIssuer()
    auth = fallback(ClientCredentials("cid", "secret", token_url=TOKEN_URL))
    with sync_client(issuer, auth) as client:
        response = client.get(API_URL)
    assert response.status_code == 200
    assert issuer.api_tokens == ["tok-1"]


def test_anonymous_fallback_degrades_when_the_exchange_is_rejected() -> None:
    issuer = TokenIssuer(token_status=400)
    auth = fallback(ClientCredentials("cid", "secret", token_url=TOKEN_URL))
    with sync_client(issuer, auth) as client, pytest.warns(UserWarning, match="Falling back."):
        response = client.get(API_URL)
    assert response.status_code == 200
    assert issuer.api_tokens == [""]


def test_anonymous_fallback_warns_once_and_stops_exchanging() -> None:
    issuer = TokenIssuer(token_status=400)
    auth = fallback(ClientCredentials("cid", "secret", token_url=TOKEN_URL))
    with sync_client(issuer, auth) as client:
        with pytest.warns(UserWarning):
            client.get(API_URL)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            client.get(API_URL)
    assert len(issuer.token_requests) == 1
    assert issuer.api_tokens == ["", ""]


def test_anonymous_fallback_raises_once_the_request_has_been_sent() -> None:
    """A rejection after the request went out is a real failure, not a spent login."""
    issuer = TokenIssuer()
    auth = fallback(ClientCredentials("cid", "secret", token_url=TOKEN_URL))
    with sync_client(issuer, auth) as client:
        client.get(API_URL)
        issuer.rejected_tokens.update({"tok-1", "tok-2"})
        with pytest.raises(AuthenticationError):
            client.get(API_URL)


async def test_anonymous_fallback_degrades_on_the_async_surface() -> None:
    issuer = TokenIssuer(token_status=400)
    auth = fallback(ClientCredentials("cid", "secret", token_url=TOKEN_URL))
    async with async_client(issuer, auth) as client:
        with pytest.warns(UserWarning, match="Falling back."):
            response = await client.get(API_URL)
        await client.get(API_URL)
    assert response.status_code == 200
    assert issuer.api_tokens == ["", ""]
    assert len(issuer.token_requests) == 1


async def test_anonymous_fallback_raises_after_an_async_request_has_been_sent() -> None:
    issuer = TokenIssuer()
    auth = fallback(ClientCredentials("cid", "secret", token_url=TOKEN_URL))
    async with async_client(issuer, auth) as client:
        await client.get(API_URL)
        issuer.rejected_tokens.update({"tok-1", "tok-2"})
        with pytest.raises(AuthenticationError):
            await client.get(API_URL)
