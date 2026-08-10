"""Auth and base-URL resolution for the unified client.

Resolution when ``auth=`` is omitted follows the binding chain
(explicit beats ambient, machine beats human):

1. ``$BOOKSHELF_TOKEN`` as a static bearer
2. ``$BOOKSHELF_CLIENT_ID`` + ``$BOOKSHELF_CLIENT_SECRET`` as client credentials,
   minted at ``$BOOKSHELF_TOKEN_URL``
3. the stored active credential for the deployment, refreshed by kind:
   a WorkOS user pair through the refresh-token grant,
   an agent record through its identity assertion
4. unauthenticated (public reads)

A stored credential the issuer refuses to refresh falls through to step 4 with a warning,
because a spent login must not cost the caller the public data it never needed a login for.

``auth=`` also accepts a provider instance or a bare token string,
and an explicit ``auth=None`` stays unauthenticated.
"""

import enum
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import httpx

from bookshelf._core import credentials, oauth
from bookshelf._core.auth import (
    AnonymousFallback,
    BsatAssertion,
    ClientCredentials,
    RefreshTokenExchange,
    StaticToken,
    TokenProvider,
)
from bookshelf._core.credentials import CredentialKind
from bookshelf._core.errors import AuthConfigurationError

PRODUCTION_API_URL = "https://api.climateresource.com.au/bookshelf"

_SPENT_CREDENTIAL_MESSAGE = (
    "The stored Bookshelf login could not be refreshed, "
    "so this client is continuing anonymously and only public data is reachable. "
    "Run 'bookshelf auth logout' to discard the stored credential, "
    "or 'bookshelf auth login' to claim a fresh one "
    "('bookshelf auth login --agent --claim --email you@org.com' for an agent identity)."
)


class _Unset(enum.Enum):
    """Sentinel distinguishing an omitted ``auth=`` from an explicit ``auth=None``."""

    UNSET = enum.auto()


UNSET = _Unset.UNSET

AuthInput = httpx.Auth | str | None | _Unset


class CredentialSource(enum.StrEnum):
    """Which step of the ambient resolution chain supplied the credential."""

    ENV_TOKEN = "env_token"
    CLIENT_CREDENTIALS = "client_credentials"
    STORED_LOGIN = "stored_login"
    NONE = "none"


def resolve_base_url(base_url: str | None) -> str:
    """Resolve the API base URL.

    The argument wins, then ``$BOOKSHELF_URL`` (canonical),
    then ``$BOOKSHELF_API_URL`` (accepted alias), then production.
    The result never carries a trailing slash.
    """
    return (
        base_url
        or os.environ.get("BOOKSHELF_URL")
        or os.environ.get("BOOKSHELF_API_URL")
        or PRODUCTION_API_URL
    ).rstrip("/")


def resolve_auth(auth: AuthInput, *, base_url: str | None = None) -> httpx.Auth | None:
    """Coerce the constructor's ``auth`` value into an ``httpx.Auth`` or ``None``.

    ``base_url`` scopes the stored-credential step to one deployment,
    so a staging client never sends a production login.
    """
    if isinstance(auth, _Unset):
        return _auth_from_environment(base_url)
    if isinstance(auth, str):
        return StaticToken(auth)
    return auth


def resolve_ambient_credential(
    base_url: str | None = None,
) -> tuple[CredentialSource, credentials.StoredCredentials | None]:
    """Walk the ambient resolution chain once.

    Returns the winning step and, for the stored-login step, the record it found,
    so callers need no second store or keychain read.
    """
    if os.environ.get("BOOKSHELF_TOKEN"):
        return CredentialSource.ENV_TOKEN, None
    if os.environ.get("BOOKSHELF_CLIENT_ID") and os.environ.get("BOOKSHELF_CLIENT_SECRET"):
        return CredentialSource.CLIENT_CREDENTIALS, None
    stored = credentials.load_credentials(base_url)
    if stored is not None:
        return CredentialSource.STORED_LOGIN, stored
    return CredentialSource.NONE, None


def resolve_credential_source(base_url: str | None = None) -> CredentialSource:
    """Report which resolution step would supply the ambient credential."""
    return resolve_ambient_credential(base_url)[0]


def _auth_from_environment(base_url: str | None) -> httpx.Auth | None:
    source, stored = resolve_ambient_credential(base_url)
    if source is CredentialSource.ENV_TOKEN:
        return StaticToken(os.environ["BOOKSHELF_TOKEN"])
    if source is CredentialSource.CLIENT_CREDENTIALS:
        token_url = os.environ.get("BOOKSHELF_TOKEN_URL")
        if not token_url:
            raise AuthConfigurationError(
                "BOOKSHELF_CLIENT_ID and BOOKSHELF_CLIENT_SECRET are set "
                "but BOOKSHELF_TOKEN_URL is not. "
                "Set BOOKSHELF_TOKEN_URL to the issuer's client-credentials token endpoint."
            )
        return ClientCredentials(
            os.environ["BOOKSHELF_CLIENT_ID"],
            os.environ["BOOKSHELF_CLIENT_SECRET"],
            token_url=token_url,
        )
    if stored is not None:
        return AnonymousFallback(auth_from_stored(stored), message=_SPENT_CREDENTIAL_MESSAGE)
    return None


def auth_from_stored(stored: credentials.StoredCredentials) -> TokenProvider:
    """Build the refreshing provider matching one stored credential record."""
    if stored.kind is CredentialKind.AGENT and stored.identity_assertion is not None:
        return _agent_auth_from_stored(stored)

    if stored.refresh_token is None:
        return StaticToken(stored.access_token)

    # An agent record with no assertion is served by the refresh-token grant,
    # so what comes back is a refresh token and the rotation lands as a user record.
    return _user_auth_from_stored(replace(stored, kind=CredentialKind.USER))


def _user_auth_from_stored(stored: credentials.StoredCredentials) -> RefreshTokenExchange:
    assert stored.refresh_token is not None
    client_id = oauth.workos_client_id(stored.api_url)
    if client_id is None:
        raise AuthConfigurationError(
            "Stored credentials carry a refresh token but no WorkOS client ID is available, "
            "so they cannot be refreshed and would expire mid-process. "
            "Set BOOKSHELF_WORKOS_CLIENT_ID to your WorkOS client ID, "
            "or pass an explicit auth= provider."
        )

    return RefreshTokenExchange(
        stored.access_token,
        stored.refresh_token,
        token_url=f"{oauth.get_workos_base_url()}/user_management/authenticate",
        client_id=client_id,
        expires_at=stored.expires_at.timestamp() if stored.expires_at is not None else None,
        on_rotate=_rotation_sink(stored),
    )


def _agent_auth_from_stored(stored: credentials.StoredCredentials) -> BsatAssertion:
    assert stored.identity_assertion is not None
    return BsatAssertion(
        stored.identity_assertion,
        base_url=stored.api_url,
        access_token=stored.access_token,
        expires_at=stored.expires_at.timestamp() if stored.expires_at is not None else None,
        on_rotate=_rotation_sink(stored),
    )


def _rotation_sink(
    stored: credentials.StoredCredentials,
) -> Callable[[str, str | None, float | None], None]:
    """Build the callback that writes a rotated credential back over the record it came from.

    Both providers rotate one secret alongside the access token,
    a refresh token for a user and a reissued identity assertion for an agent,
    so they hand it over in the same position.
    """

    def persist(access_token: str, secret: str | None, expires_at: float | None) -> None:
        moment = datetime.fromtimestamp(expires_at, tz=UTC) if expires_at is not None else None
        rotated = (
            stored.with_token(access_token, expires_at=moment, identity_assertion=secret)
            if stored.kind is CredentialKind.AGENT
            else stored.with_token(access_token, expires_at=moment, refresh_token=secret)
        )
        credentials.save_record(rotated)

    return persist


__all__ = [
    "PRODUCTION_API_URL",
    "UNSET",
    "AuthInput",
    "CredentialSource",
    "auth_from_stored",
    "resolve_ambient_credential",
    "resolve_auth",
    "resolve_base_url",
    "resolve_credential_source",
]
