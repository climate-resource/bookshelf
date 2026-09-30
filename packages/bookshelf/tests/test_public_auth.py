"""Tests for the public ``bookshelf.auth`` surface other services build on."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

import bookshelf.auth
from bookshelf import AuthenticationError
from bookshelf._core import credentials
from bookshelf._core.auth import AnonymousFallback
from bookshelf.auth import (
    ClientCredentials,
    RefreshTokenExchange,
    StaticToken,
    access_token,
    default_auth,
)

API = "https://bookshelf.test"


@pytest.fixture(autouse=True)
def clean_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BOOKSHELF_TOKEN",
        "BOOKSHELF_AUTH",
        "BOOKSHELF_CLIENT_ID",
        "BOOKSHELF_CLIENT_SECRET",
        "BOOKSHELF_TOKEN_URL",
        "BOOKSHELF_URL",
        "BOOKSHELF_API_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client_test")
    monkeypatch.setattr(credentials, "credentials_path", lambda: tmp_path / "credentials.json")


def spent_login() -> None:
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="stored-tok",
            api_url=API,
            refresh_token="rt-spent",
            expires_at=datetime.fromtimestamp(0, tz=UTC),
        )
    )


def refusing_issuer(seen: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authenticate"):
            return httpx.Response(
                400, json={"error_description": "Refresh token already exchanged"}
            )
        seen.append(request.headers.get("Authorization", ""))
        return httpx.Response(200)

    return httpx.MockTransport(handler)


def test_no_credential_is_none() -> None:
    assert default_auth() is None
    assert access_token() is None


def test_env_token_is_handed_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_TOKEN", "env-tok")

    assert isinstance(default_auth(), StaticToken)
    assert access_token() == "env-tok"


def test_machine_credential_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_CLIENT_ID", "cid")
    monkeypatch.setenv("BOOKSHELF_CLIENT_SECRET", "secret")
    monkeypatch.setenv("BOOKSHELF_TOKEN_URL", "https://issuer.test/token")

    assert isinstance(default_auth(), ClientCredentials)


def test_stored_login_is_scoped_to_the_named_deployment() -> None:
    spent_login()

    auth = default_auth(f"{API}/")

    assert isinstance(auth, AnonymousFallback)
    assert isinstance(auth.inner, RefreshTokenExchange)
    assert default_auth("https://other.test") is None


def test_default_auth_signs_requests_to_another_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_TOKEN", "env-tok")
    seen: list[str] = []

    with httpx.Client(transport=refusing_issuer(seen), auth=default_auth()) as client:
        client.get("https://other-service.test/v1/me")

    assert seen == ["Bearer env-tok"]


def test_a_spent_login_degrades_by_default() -> None:
    spent_login()
    seen: list[str] = []

    with (
        httpx.Client(transport=refusing_issuer(seen), auth=default_auth(API)) as client,
        pytest.warns(UserWarning),
    ):
        client.get("https://other-service.test/v1/me")

    assert seen == [""]


def test_a_strict_default_auth_raises_for_a_spent_login() -> None:
    spent_login()
    seen: list[str] = []

    with (
        httpx.Client(
            transport=refusing_issuer(seen), auth=default_auth(API, strict=True)
        ) as client,
        pytest.raises(AuthenticationError, match="already exchanged"),
    ):
        client.get("https://other-service.test/v1/me")

    assert seen == []


def test_access_token_raises_for_a_spent_login(monkeypatch: pytest.MonkeyPatch) -> None:
    spent_login()
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **_kwargs: real_client(transport=refusing_issuer([]))
    )

    with pytest.raises(AuthenticationError):
        access_token(API)


def test_the_public_names_are_exactly_these() -> None:
    assert set(bookshelf.auth.__all__) == {
        "ActionsOidcToken",
        "ActionsTokenError",
        "AuthConfigurationError",
        "BsatAssertion",
        "ClientCredentials",
        "RefreshTokenExchange",
        "StaticToken",
        "TokenProvider",
        "access_token",
        "default_auth",
    }
    assert all(hasattr(bookshelf.auth, name) for name in bookshelf.auth.__all__)
