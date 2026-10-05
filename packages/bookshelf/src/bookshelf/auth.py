"""Bookshelf credentials for use against other Climate Resource services.

The credential is resolved exactly as a ``Bookshelf`` client resolves it.
"""

import httpx

from bookshelf._core.actions_oidc import ActionsTokenError
from bookshelf._core.auth import (
    ActionsOidcToken,
    ClientCredentials,
    RefreshTokenExchange,
    StaticToken,
    TokenProvider,
)
from bookshelf._core.config import resolve_base_url
from bookshelf._core.errors import AuthConfigurationError
from bookshelf._core.resolution import resolve_credential


def default_auth(api_url: str | None = None, *, strict: bool = False) -> httpx.Auth | None:
    """Return the credential a ``Bookshelf`` client would use, or ``None`` when there is none.

    Tokens refresh ahead of expiry and once after a 401.
    A stored login whose refresh fails degrades to unauthenticated requests with a warning,
    unless ``strict`` asks for the :class:`~bookshelf.AuthenticationError` instead.
    ``api_url`` picks which Bookshelf deployment's stored login to use.
    """
    return resolve_credential(resolve_base_url(api_url, source="api_url")).auth(strict=strict)


def access_token(api_url: str | None = None, *, timeout: float = 30.0) -> str | None:
    """Return a current bearer token, refreshing it first when one is due.

    Returns ``None`` when no credential is configured.
    ``timeout`` bounds the token exchange, in seconds.
    Raises :class:`~bookshelf.AuthenticationError` when the credential cannot be refreshed.
    A token rotated by the refresh is written back to the credential store.
    """
    provider = resolve_credential(resolve_base_url(api_url, source="api_url")).token_provider()
    if provider is None:
        return None
    with httpx.Client(timeout=timeout) as client:
        return provider.access_token(client.send)


__all__ = [
    "ActionsOidcToken",
    "ActionsTokenError",
    "AuthConfigurationError",
    "ClientCredentials",
    "RefreshTokenExchange",
    "StaticToken",
    "TokenProvider",
    "access_token",
    "default_auth",
]
