"""Credential providers for the Bookshelf SDK.

Every provider is an ``httpx.Auth`` whose flow logic is sans-io:
a token refresh is expressed as a yielded request,
so one provider object serves both the sync and async client surfaces.
Token state lives in the provider,
so multiple clients can share one provider and refresh once between them.

Refresh mechanics shared by the exchanging providers:

- proactive refresh when the token expires within :data:`REFRESH_LEEWAY` seconds,
  checked at request time inside the flow
- on a 401 despite that, refresh once and replay once, a second 401 raises
  :class:`~bookshelf._core.errors.AuthenticationError`
- single-flight refresh behind per-surface locks, because parallel refreshes
  with a single-use rotating refresh token break the rotation chain
- no background refresh task

The 401 replay re-sends the original request object,
so a request carrying a consumed stream body cannot be replayed.
Every operation on this client sends bytes or JSON, and presigned uploads skip auth entirely.
"""

import asyncio
import base64
import binascii
import json
import threading
import time
import warnings
from collections.abc import AsyncGenerator, Callable, Generator

import httpx

from bookshelf._core.errors import AuthenticationError

# Refresh proactively when the access token expires within this window (seconds).
REFRESH_LEEWAY = 300.0

JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"


def decode_jwt_expiry(token: str) -> float | None:
    """Best-effort decode of a JWT ``exp`` claim into epoch seconds.

    No signature verification is performed, the server verifies the token.
    The value is only a client-side hint for when to refresh.
    Returns ``None`` for non-JWT or otherwise unparseable tokens.
    """
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        if not isinstance(payload, dict):
            return None
        exp = payload.get("exp")
        return None if exp is None else float(exp)
    except (IndexError, ValueError, TypeError, binascii.Error):
        return None


class StaticToken(httpx.Auth):
    """A fixed bearer token with no refresh behaviour."""

    def __init__(self, token: str) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


class _RefreshingAuth(httpx.Auth):
    """Shared refresh machinery for the exchanging providers.

    Subclasses supply the token-endpoint request via :meth:`_refresh_request`
    and may hook :meth:`_handle_token_payload` for grant-specific state
    (rotated refresh tokens, reissued assertions, persistence callbacks).
    Both hooks are sans-io, the flow drivers only add locking.
    """

    # Deliberately not requires_response_body.
    # That would make httpx buffer every response body
    # and defeat streamed resource downloads.
    # Only the token response is read, explicitly, inside the flow.

    def __init__(self, *, access_token: str | None = None, expires_at: float | None = None) -> None:
        self._access_token = access_token
        if expires_at is None and access_token is not None:
            expires_at = decode_jwt_expiry(access_token)
        self._expires_at = expires_at
        # A handed-in token of unknown expiry may already be dead.
        # It is refreshed before first use.
        # A token this provider minted is not.
        self._minted = False
        self._sync_lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    def _refresh_request(self) -> httpx.Request:
        raise NotImplementedError

    def _handle_token_payload(self, payload: dict[str, object]) -> None:
        """Grant-specific handling of a successful token response."""

    def _needs_refresh(self) -> bool:
        if self._access_token is None:
            return True
        if self._expires_at is None:
            return not self._minted
        return self._expires_at - time.time() < REFRESH_LEEWAY

    def _apply_token_response(self, response: httpx.Response) -> None:
        if not response.is_success:
            raise AuthenticationError(
                f"Token refresh failed: {_error_detail(response)}",
                status_code=response.status_code,
                request_method="POST",
                request_url=str(response.request.url),
            )
        payload = json.loads(response.content)
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise AuthenticationError(
                "Token response carried no access_token.",
                status_code=response.status_code,
                request_method="POST",
                request_url=str(response.request.url),
            )
        self._access_token = access_token
        self._minted = True
        expires_in = payload.get("expires_in")
        if isinstance(expires_in, int | float):
            self._expires_at = time.time() + float(expires_in)
        else:
            self._expires_at = decode_jwt_expiry(access_token)
        self._handle_token_payload(payload)

    def _authorized(self, request: httpx.Request) -> httpx.Request:
        """Stamp the current access token onto *request*."""
        token = self._access_token
        if token is None:
            raise AuthenticationError(
                "No access token is available after a refresh.",
                status_code=401,
                request_method=request.method,
                request_url=str(request.url),
            )
        request.headers["Authorization"] = f"Bearer {token}"
        return request

    @staticmethod
    def _raise_still_unauthorized(request: httpx.Request, response: httpx.Response) -> None:
        raise AuthenticationError(
            "Request was rejected with 401 again after a token refresh.",
            status_code=response.status_code,
            request_method=request.method,
            request_url=str(request.url),
        )

    def sync_auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        if self._needs_refresh():
            # The lock is held across the refresh yield,
            # so concurrent callers wait for one exchange
            # instead of racing their own.
            with self._sync_lock:
                if self._needs_refresh():
                    token_response = yield self._refresh_request()
                    token_response.read()
                    self._apply_token_response(token_response)
        sent_token = self._access_token
        response = yield self._authorized(request)
        if response.status_code != 401:
            return
        with self._sync_lock:
            # Another caller may already have replaced the rejected token.
            if self._access_token == sent_token:
                token_response = yield self._refresh_request()
                token_response.read()
                self._apply_token_response(token_response)
        response = yield self._authorized(request)
        if response.status_code == 401:
            self._raise_still_unauthorized(request, response)

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if self._needs_refresh():
            async with self._async_lock:
                if self._needs_refresh():
                    token_response = yield self._refresh_request()
                    await token_response.aread()
                    self._apply_token_response(token_response)
        sent_token = self._access_token
        response = yield self._authorized(request)
        if response.status_code != 401:
            return
        async with self._async_lock:
            # Another caller may already have replaced the rejected token.
            if self._access_token == sent_token:
                token_response = yield self._refresh_request()
                await token_response.aread()
                self._apply_token_response(token_response)
        response = yield self._authorized(request)
        if response.status_code == 401:
            self._raise_still_unauthorized(request, response)


class RefreshTokenExchange(_RefreshingAuth):
    """A user access/refresh token pair, refreshed with the ``refresh_token`` grant.

    The issuer rotates the refresh token on each use,
    so every successful exchange invokes ``on_rotate`` with the new
    ``(access_token, refresh_token, expires_at)`` for persistence.
    """

    def __init__(
        self,
        access_token: str | None,
        refresh_token: str,
        *,
        token_url: str,
        client_id: str,
        expires_at: float | None = None,
        on_rotate: Callable[[str, str | None, float | None], None] | None = None,
    ) -> None:
        super().__init__(access_token=access_token, expires_at=expires_at)
        self._refresh_token = refresh_token
        self._token_url = token_url
        self._client_id = client_id
        self._on_rotate = on_rotate

    def _refresh_request(self) -> httpx.Request:
        return httpx.Request(
            "POST",
            self._token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
            },
        )

    def _handle_token_payload(self, payload: dict[str, object]) -> None:
        rotated = payload.get("refresh_token")
        if isinstance(rotated, str) and rotated:
            self._refresh_token = rotated
        if self._on_rotate is not None:
            assert self._access_token is not None
            self._on_rotate(self._access_token, self._refresh_token, self._expires_at)


class ClientCredentials(_RefreshingAuth):
    """An OAuth2 ``client_credentials`` machine credential.

    A refresh is a plain re-POST of the credential pair, there is nothing to persist.
    """

    def __init__(self, client_id: str, client_secret: str, *, token_url: str) -> None:
        super().__init__()
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url

    def _refresh_request(self) -> httpx.Request:
        return httpx.Request(
            "POST",
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )


class BsatAssertion(_RefreshingAuth):
    """An agent identity assertion exchanged via the ``jwt-bearer`` grant.

    The token endpoint may reissue the assertion alongside the access token,
    in which case the reissued assertion replaces the stored one.
    Every successful exchange invokes ``on_rotate`` with the new
    ``(access_token, assertion, expires_at)`` for persistence,
    because a reissued assertion invalidates the stored one.

    Give either ``base_url`` (the API's own ``/oauth2/token`` is derived from it)
    or an explicit ``token_url``.
    """

    def __init__(
        self,
        assertion: str,
        *,
        base_url: str | None = None,
        token_url: str | None = None,
        access_token: str | None = None,
        expires_at: float | None = None,
        on_rotate: Callable[[str, str, float | None], None] | None = None,
    ) -> None:
        super().__init__(access_token=access_token, expires_at=expires_at)
        if (base_url is None) == (token_url is None):
            raise ValueError("Give exactly one of base_url or token_url.")
        self._assertion = assertion
        self._token_url = token_url or f"{str(base_url).rstrip('/')}/oauth2/token"
        self._on_rotate = on_rotate

    def _refresh_request(self) -> httpx.Request:
        return httpx.Request(
            "POST",
            self._token_url,
            data={"grant_type": JWT_BEARER_GRANT, "assertion": self._assertion},
        )

    def _handle_token_payload(self, payload: dict[str, object]) -> None:
        reissued = payload.get("identity_assertion")
        if isinstance(reissued, str) and reissued:
            self._assertion = reissued
        if self._on_rotate is not None:
            assert self._access_token is not None
            self._on_rotate(self._access_token, self._assertion, self._expires_at)


class AnonymousFallback(httpx.Auth):
    """Wrap a provider so a rejected token exchange degrades to unauthenticated requests.

    A stored login whose refresh the issuer rejects is spent, and there is nothing
    the process can do about it, so insisting on it would deny the caller the public
    data that needs no credential at all.
    Only the exchange that runs before the wrapped request goes out is covered.
    Once a request has been sent under a token, a later rejection is a real failure
    and is raised.

    The first degradation warns with ``message``, and the wrapper stays anonymous
    afterwards so one dead credential costs one doomed exchange per provider.
    """

    def __init__(self, inner: httpx.Auth, *, message: str) -> None:
        self.inner = inner
        self._message = message
        self._degraded = False

    def _degrade(self, exc: AuthenticationError) -> None:
        self._degraded = True
        warnings.warn(f"{self._message} The exchange failed with: {exc}", stacklevel=3)

    def sync_auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        if self._degraded:
            yield request
            return
        flow = self.inner.sync_auth_flow(request)
        sent = False
        try:
            outgoing = next(flow)
            while True:
                sent = sent or outgoing is request
                response = yield outgoing
                outgoing = flow.send(response)
        except StopIteration:
            return
        except AuthenticationError as exc:
            if sent:
                raise
            self._degrade(exc)
        yield request

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if self._degraded:
            yield request
            return
        flow = self.inner.async_auth_flow(request)
        sent = False
        try:
            outgoing = await anext(flow)
            while True:
                sent = sent or outgoing is request
                response = yield outgoing
                outgoing = await flow.asend(response)
        except StopAsyncIteration:
            return
        except AuthenticationError as exc:
            if sent:
                raise
            self._degrade(exc)
        yield request


def _error_detail(response: httpx.Response) -> str:
    """Extract a human-readable detail from a failed token response."""
    try:
        body = json.loads(response.content)
    except ValueError:
        return response.text[:200] or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        for key in ("error_description", "message", "detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
    return json.dumps(body)[:200]


__all__ = [
    "REFRESH_LEEWAY",
    "AnonymousFallback",
    "BsatAssertion",
    "ClientCredentials",
    "RefreshTokenExchange",
    "StaticToken",
    "decode_jwt_expiry",
]
