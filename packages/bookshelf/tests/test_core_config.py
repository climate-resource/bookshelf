"""Tests for auth and base-URL resolution: explicit beats ambient, machine beats human."""

import time
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from bookshelf._core import config, credentials, oauth
from bookshelf._core.auth import (
    AnonymousFallback,
    ClientCredentials,
    RefreshTokenExchange,
    StaticToken,
)
from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import AuthConfigurationError


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BOOKSHELF_TOKEN",
        "BOOKSHELF_CLIENT_ID",
        "BOOKSHELF_CLIENT_SECRET",
        "BOOKSHELF_TOKEN_URL",
        "BOOKSHELF_API_URL",
        "BOOKSHELF_WORKOS_CLIENT_ID",
        "BOOKSHELF_WORKOS_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(credentials, "load_credentials", lambda _api_url=None: None)


def stored(
    monkeypatch: pytest.MonkeyPatch, *, refresh_token: str | None = "rt-stored"
) -> credentials.StoredCredentials:
    creds = credentials.StoredCredentials(
        access_token="stored-tok",
        token_type="bearer",
        expires_at=datetime.fromtimestamp(time.time() + 10_000, tz=UTC),
        api_url="https://bookshelf-staging.ovh.climateresource.com.au",
        refresh_token=refresh_token,
        subject="reader@example.com",
        organization_id="org_123",
    )
    monkeypatch.setattr(credentials, "load_credentials", lambda _api_url=None: creds)
    return creds


def test_base_url_argument_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_API_URL", "https://env.test")
    assert config.resolve_base_url("https://arg.test") == "https://arg.test"


def test_base_url_env_beats_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_API_URL", "https://env.test")
    assert config.resolve_base_url(None) == "https://env.test"


def test_base_url_defaults_to_production() -> None:
    assert config.resolve_base_url(None) == "https://api.climateresource.com.au/bookshelf"


def test_bare_string_coerces_to_static_token() -> None:
    auth = config.resolve_auth("bsat_x")
    assert isinstance(auth, StaticToken)


def test_provider_instance_passes_through() -> None:
    provider = ClientCredentials("cid", "secret", token_url="https://issuer.test/token")
    assert config.resolve_auth(provider) is provider


def test_explicit_none_stays_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_TOKEN", "ambient")
    assert config.resolve_auth(None) is None


def test_env_token_wins_over_stored_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    stored(monkeypatch)
    monkeypatch.setenv("BOOKSHELF_TOKEN", "env-tok")
    auth = config.resolve_auth(config.UNSET)
    assert isinstance(auth, StaticToken)
    assert auth._token == "env-tok"


def test_client_credentials_beat_stored_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    stored(monkeypatch)
    monkeypatch.setenv("BOOKSHELF_CLIENT_ID", "cid")
    monkeypatch.setenv("BOOKSHELF_CLIENT_SECRET", "secret")
    monkeypatch.setenv("BOOKSHELF_TOKEN_URL", "https://issuer.test/token")
    auth = config.resolve_auth(config.UNSET)
    assert isinstance(auth, ClientCredentials)


def test_client_credentials_without_token_url_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKSHELF_CLIENT_ID", "cid")
    monkeypatch.setenv("BOOKSHELF_CLIENT_SECRET", "secret")
    with pytest.raises(AuthConfigurationError):
        config.resolve_auth(config.UNSET)


def test_stored_credentials_resolve_to_refresh_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored(monkeypatch)
    auth = config.resolve_auth(config.UNSET)
    assert isinstance(auth, AnonymousFallback)
    assert isinstance(auth.inner, RefreshTokenExchange)


def test_stored_refresh_exchange_persists_rotations(monkeypatch: pytest.MonkeyPatch) -> None:
    stored(monkeypatch)
    saved: list[credentials.StoredCredentials] = []
    monkeypatch.setattr(credentials, "save_record", saved.append)
    auth = config.resolve_auth(config.UNSET)
    assert isinstance(auth, AnonymousFallback)
    assert isinstance(auth.inner, RefreshTokenExchange)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authenticate"):
            return httpx.Response(
                200,
                json={"access_token": "new-tok", "refresh_token": "rt-2", "expires_in": 3600},
            )
        return httpx.Response(200, json={"ok": True})

    auth.inner._expires_at = 0.0
    with httpx.Client(transport=httpx.MockTransport(handler), auth=auth) as client:
        client.get("https://bookshelf.test/v1/books")
    assert saved[0].access_token == "new-tok"
    assert saved[0].refresh_token == "rt-2"
    # The record the rotation came from is what is written back.
    assert saved[0].subject == "reader@example.com"
    assert saved[0].organization_id == "org_123"


def test_an_agent_record_without_an_assertion_rotates_as_a_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rotation follows the provider that was built, not the record's own kind.

    An agent record with no assertion is served by the refresh-token provider,
    so what comes back is a refresh token and it has to be stored as one.
    """
    agent_record = replace(
        stored(monkeypatch), kind=credentials.CredentialKind.AGENT, identity_assertion=None
    )
    monkeypatch.setattr(credentials, "load_credentials", lambda _api_url=None: agent_record)
    saved: list[credentials.StoredCredentials] = []
    monkeypatch.setattr(credentials, "save_record", saved.append)
    auth = config.resolve_auth(config.UNSET)
    assert isinstance(auth, AnonymousFallback)
    assert isinstance(auth.inner, RefreshTokenExchange)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authenticate"):
            return httpx.Response(
                200,
                json={"access_token": "new-tok", "refresh_token": "rt-2", "expires_in": 3600},
            )
        return httpx.Response(200, json={"ok": True})

    auth.inner._expires_at = 0.0
    with httpx.Client(transport=httpx.MockTransport(handler), auth=auth) as client:
        client.get("https://bookshelf.test/v1/books")

    assert saved[0].kind is credentials.CredentialKind.USER
    assert saved[0].refresh_token == "rt-2"
    assert saved[0].identity_assertion is None


def test_stored_without_workos_client_id_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silently degrading to a static token would kill rotation mid-process."""
    stored(monkeypatch)
    monkeypatch.setattr(oauth, "resolve_workos_client_id", lambda _api_url: None)
    with pytest.raises(AuthConfigurationError):
        config.resolve_auth(config.UNSET)


def test_stored_without_refresh_token_resolves_to_static(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creds = stored(monkeypatch, refresh_token=None)
    auth = config.resolve_auth(config.UNSET)
    assert isinstance(auth, AnonymousFallback)
    assert isinstance(auth.inner, StaticToken)
    assert auth.inner._token == creds.access_token


def test_no_ambient_credentials_resolves_to_none() -> None:
    assert config.resolve_auth(config.UNSET) is None


def test_client_constructor_coerces_and_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_API_URL", "https://env.test")
    client = BookshelfClient(auth="bsat_x")
    assert client._base_url == "https://env.test"
    assert isinstance(client._auth, StaticToken)

    client = BookshelfClient("https://arg.test")
    assert client._base_url == "https://arg.test"
    assert client._auth is None


def test_a_spent_stored_login_degrades_to_anonymous(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refresh the issuer refuses must not cost the caller the public books."""
    stored(monkeypatch)
    auth = config.resolve_auth(config.UNSET)
    assert isinstance(auth, AnonymousFallback)
    auth.inner._expires_at = 0.0

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authenticate"):
            return httpx.Response(
                400, json={"error_description": "Refresh token already exchanged"}
            )
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"ok": True})

    with (
        httpx.Client(transport=httpx.MockTransport(handler), auth=auth) as client,
        pytest.warns(UserWarning) as record,
    ):
        response = client.get("https://bookshelf.test/v1/books")

    assert response.status_code == 200
    assert seen == [""]
    warning = str(record[0].message)
    assert "bookshelf auth logout" in warning
    assert "bookshelf auth login" in warning
    assert "Refresh token already exchanged" in warning
