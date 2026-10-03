"""Which credential a process uses for one Bookshelf deployment.

The chain is walked once, first answer wins (explicit beats ambient, machine beats human):

1. ``$BOOKSHELF_TOKEN`` as a static bearer
2. a GitHub Actions OIDC token, only when ``$BOOKSHELF_AUTH`` asks for one
3. ``$BOOKSHELF_CLIENT_ID`` + ``$BOOKSHELF_CLIENT_SECRET`` as client credentials,
   minted at ``$BOOKSHELF_TOKEN_URL``
4. the stored active credential for the deployment, refreshed by kind:
   a WorkOS user pair through the refresh-token grant,
   an agent record through its identity assertion
5. unauthenticated (public reads)

Step 2 is opt-in rather than ambient,
because a job holding ``id-token: write`` for something else must never mint for Bookshelf.

A stored credential the issuer refuses to refresh falls through to step 5 with a warning,
because a spent login must not cost the caller the public data it never needed a login for.
"""

import enum
import os
import threading
import warnings
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx

from bookshelf._core import oauth
from bookshelf._core.actions_oidc import READ_AUDIENCE
from bookshelf._core.auth import (
    ActionsOidcToken,
    AnonymousFallback,
    BsatAssertion,
    ClientCredentials,
    RefreshTokenExchange,
    StaticToken,
    TokenProvider,
    decode_jwt_expiry,
)
from bookshelf._core.config import AUTH_MODE_VAR, GITHUB_ACTIONS_AUTH_MODE
from bookshelf._core.credentials import (
    CredentialKind,
    CredentialStore,
    StoredCredentials,
    default_store,
)
from bookshelf._core.errors import AuthConfigurationError

_SPENT_CREDENTIAL_MESSAGE = (
    "The stored Bookshelf login could not be refreshed, "
    "so this client is continuing anonymously and only public data is reachable. "
    "Run 'bookshelf auth logout' to discard the stored credential, "
    "or 'bookshelf auth login' to claim a fresh one "
    "('bookshelf auth login --agent --claim --email you@org.com' for an agent identity)."
)

LOGIN_REMEDY = (
    "Run 'bookshelf auth login' to sign in, "
    "or 'bookshelf auth login --agent' to register an agent identity."
)


class CredentialSource(enum.StrEnum):
    """Which step of the resolution chain supplied the credential."""

    ENV_TOKEN = "env_token"  # noqa: S105
    ACTIONS_OIDC = "actions_oidc"
    CLIENT_CREDENTIALS = "client_credentials"
    STORED_LOGIN = "stored_login"
    NONE = "none"


# How a message names each machine credential, and what to do when the API refuses it.
_MACHINE_SOURCES = {
    CredentialSource.ENV_TOKEN: (
        "$BOOKSHELF_TOKEN",
        "Replace $BOOKSHELF_TOKEN with a current token, or unset it.",
    ),
    CredentialSource.ACTIONS_OIDC: (
        "the job's GitHub Actions OIDC token",
        "Give the job the 'id-token: write' permission.",
    ),
    CredentialSource.CLIENT_CREDENTIALS: (
        "the client credentials in $BOOKSHELF_CLIENT_ID",
        "Check BOOKSHELF_CLIENT_ID, BOOKSHELF_CLIENT_SECRET "
        "and BOOKSHELF_TOKEN_URL against the issuer.",
    ),
}


@dataclass(frozen=True)
class CredentialDescription:
    """What a resolved credential is, reported without calling the API."""

    source: CredentialSource
    kind: Literal["user", "agent", "machine", "anonymous"]
    label: str
    """How a message names the credential, e.g. ``$BOOKSHELF_TOKEN``."""
    remedy: str
    """What to do when the credential is refused."""
    subject: str | None = None
    organization_id: str | None = None
    expires_at: datetime | None = None
    claimed: bool | None = None


def github_actions_requested(environ: Mapping[str, str]) -> bool:
    """Report whether ``$BOOKSHELF_AUTH`` asks for the job's GitHub Actions OIDC token.

    Any other value is a mistake worth naming rather than silently ignoring.
    """
    mode = environ.get(AUTH_MODE_VAR, "").strip().lower()
    if not mode:
        return False
    if mode != GITHUB_ACTIONS_AUTH_MODE:
        raise AuthConfigurationError(
            f"${AUTH_MODE_VAR} is set to {mode!r}, "
            f"and the only value it takes is {GITHUB_ACTIONS_AUTH_MODE!r}."
        )
    return True


class ResolvedCredential:
    """The credential one walk of the chain chose for a deployment.

    Callers ask it for what they need rather than branching on where it came from.
    The provider is built once, so every request and printed token share its refresh state.
    """

    def __init__(
        self,
        source: CredentialSource,
        api_url: str,
        *,
        environ: Mapping[str, str],
        store: CredentialStore,
        stored: StoredCredentials | None = None,
    ) -> None:
        self.source = source
        self.api_url = api_url
        self.stored = stored
        """The record the stored-login step found, ``None`` for every other step."""
        self.store = store
        """Where the stored-login step looks, and where a rotated or fresh login is saved."""
        self._environ = environ
        self._provider: TokenProvider | None = None
        self._fallback: AnonymousFallback | None = None
        self._lock = threading.Lock()

    def shadowed_login(self) -> StoredCredentials | None:
        """Read the stored login a machine credential is overriding, if there is one."""
        if self.source not in _MACHINE_SOURCES:
            return None
        return self.store.load(self.api_url)

    def token_provider(self) -> TokenProvider | None:
        """Return the provider, strict where :meth:`auth` degrades, or ``None`` when nothing was found."""
        with self._lock:
            if self._provider is None and self.source is not CredentialSource.NONE:
                self._provider = self._build_provider()
            return self._provider

    def auth(self, *, strict: bool = False) -> httpx.Auth | None:
        """Return what requests carry.

        A stored login whose refresh is refused degrades to anonymous requests with a warning,
        unless ``strict`` asks for the :class:`~bookshelf._core.errors.AuthenticationError`.
        """
        provider = self.token_provider()
        if provider is None or strict or self.stored is None:
            return provider
        with self._lock:
            if self._fallback is None:
                self._fallback = AnonymousFallback(provider, message=_SPENT_CREDENTIAL_MESSAGE)
            return self._fallback

    def quieted(self) -> AbstractContextManager[None]:
        """Drop the spent-login warning inside the block, for a caller about to offer a login."""
        return self._fallback.quieted() if self._fallback is not None else nullcontext()

    def may_prompt_login(self) -> bool:
        """Whether an interactive login may replace this credential when the API refuses it.

        Machine credentials are verified but never replaced.
        """
        return self.source not in _MACHINE_SOURCES

    def with_login(self, record: StoredCredentials) -> "ResolvedCredential":
        """Return the credential a fresh interactive login resolves to."""
        return ResolvedCredential(
            CredentialSource.STORED_LOGIN,
            self.api_url,
            environ=self._environ,
            store=self.store,
            stored=record,
        )

    def describe(self) -> CredentialDescription:
        """Report what the credential is, offline."""
        source = self.source
        if source is CredentialSource.ENV_TOKEN:
            label, remedy = _MACHINE_SOURCES[source]
            token = self._environ["BOOKSHELF_TOKEN"]
            exp = decode_jwt_expiry(token)
            return CredentialDescription(
                source,
                kind="agent" if token.startswith("bsat_") else "user",
                label=label,
                remedy=remedy,
                expires_at=None if exp is None else datetime.fromtimestamp(exp, tz=UTC),
            )
        if source in _MACHINE_SOURCES:
            label, remedy = _MACHINE_SOURCES[source]
            return CredentialDescription(source, kind="machine", label=label, remedy=remedy)
        if self.stored is None:
            return CredentialDescription(
                source, kind="anonymous", label="no credential", remedy=LOGIN_REMEDY
            )
        stored = self.stored
        return CredentialDescription(
            source,
            kind=stored.kind.value,
            label="the stored login",
            remedy=LOGIN_REMEDY,
            subject=stored.subject,
            organization_id=stored.organization_id,
            expires_at=stored.expires_at,
            claimed=bool(stored.claimed) if stored.kind is CredentialKind.AGENT else None,
        )

    def _build_provider(self) -> TokenProvider:
        source = self.source
        if source is CredentialSource.ENV_TOKEN:
            return StaticToken(self._environ["BOOKSHELF_TOKEN"])
        if source is CredentialSource.ACTIONS_OIDC:
            return ActionsOidcToken(READ_AUDIENCE)
        if source is CredentialSource.CLIENT_CREDENTIALS:
            return _client_credentials(self._environ)
        assert self.stored is not None
        return _provider_from_stored(self.stored, self.store)


def resolve_credential(
    api_url: str,
    *,
    environ: Mapping[str, str] | None = None,
    store: CredentialStore | None = None,
) -> ResolvedCredential:
    """Walk the chain once for ``api_url``, a base URL that is already resolved."""
    environ = os.environ if environ is None else environ
    store = default_store() if store is None else store

    def resolved(
        source: CredentialSource, stored: StoredCredentials | None = None
    ) -> ResolvedCredential:
        return ResolvedCredential(source, api_url, environ=environ, store=store, stored=stored)

    # Checked first, so a mistyped mode is named even when a token wins the chain.
    github_actions = github_actions_requested(environ)
    if environ.get("BOOKSHELF_TOKEN"):
        return resolved(CredentialSource.ENV_TOKEN)
    if github_actions:
        return resolved(CredentialSource.ACTIONS_OIDC)
    if environ.get("BOOKSHELF_CLIENT_ID") and environ.get("BOOKSHELF_CLIENT_SECRET"):
        return resolved(CredentialSource.CLIENT_CREDENTIALS)
    stored = store.load(api_url)
    if stored is not None:
        return resolved(CredentialSource.STORED_LOGIN, stored)
    return resolved(CredentialSource.NONE)


def _client_credentials(environ: Mapping[str, str]) -> ClientCredentials:
    token_url = environ.get("BOOKSHELF_TOKEN_URL")
    if not token_url:
        raise AuthConfigurationError(
            "BOOKSHELF_CLIENT_ID and BOOKSHELF_CLIENT_SECRET are set "
            "but BOOKSHELF_TOKEN_URL is not. "
            "Set BOOKSHELF_TOKEN_URL to the issuer's client-credentials token endpoint."
        )
    return ClientCredentials(
        environ["BOOKSHELF_CLIENT_ID"], environ["BOOKSHELF_CLIENT_SECRET"], token_url=token_url
    )


def _provider_from_stored(stored: StoredCredentials, store: CredentialStore) -> TokenProvider:
    if store.read_only():
        # Refreshing spends a single-use secret the newer install still needs, and it could not be saved.
        warnings.warn(
            "the credentials file was written by a newer bookshelf, so its access token is used "
            "as stored and never refreshed. Upgrade bookshelf, or set BOOKSHELF_TOKEN",
            stacklevel=2,
        )
        return StaticToken(stored.access_token)
    expires_at = stored.expires_at.timestamp() if stored.expires_at is not None else None
    if stored.kind is CredentialKind.AGENT and stored.identity_assertion is not None:
        return BsatAssertion(
            stored.identity_assertion,
            base_url=stored.api_url,
            access_token=stored.access_token,
            expires_at=expires_at,
            on_rotate=_rotation_sink(stored, store),
        )

    if stored.refresh_token is None:
        return StaticToken(stored.access_token)

    client_id = oauth.resolve_workos_client_id(stored.api_url)
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
        expires_at=expires_at,
        on_rotate=_rotation_sink(stored, store),
    )


def _rotation_sink(
    stored: StoredCredentials, store: CredentialStore
) -> Callable[[str, str | None, float | None], None]:
    """Build the callback that writes each rotated credential over the one before it."""
    # An agent record with no assertion is served by the refresh-token grant, so it rotates one.
    as_agent = stored.kind is CredentialKind.AGENT and stored.identity_assertion is not None
    latest = previous = stored
    # The sync and async refresh locks are separate, so both surfaces can land here at once.
    lock = threading.Lock()

    def persist(access_token: str, secret: str | None, expires_at: float | None) -> None:
        nonlocal latest, previous
        moment = datetime.fromtimestamp(expires_at, tz=UTC) if expires_at is not None else None
        with lock:
            latest = (
                latest.with_token(access_token, expires_at=moment, identity_assertion=secret)
                if as_agent
                else latest.with_token(access_token, expires_at=moment, refresh_token=secret)
            )
            if store.rotate(previous, latest):
                previous = latest

    return persist


__all__ = [
    "LOGIN_REMEDY",
    "CredentialDescription",
    "CredentialSource",
    "ResolvedCredential",
    "github_actions_requested",
    "resolve_credential",
]
