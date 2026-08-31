"""Offline CLI authentication tests that do not require the private backend."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import keyring
import keyring.backend
import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._core import credentials

API_URL = "http://127.0.0.1:9"
runner = CliRunner()


class _MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self._values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self._values.pop((service, username), None)


@pytest.fixture(autouse=True)
def isolated_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(credentials, "credentials_path", lambda: path)
    keyring.set_keyring(_MemoryKeyring())
    monkeypatch.setenv("BOOKSHELF_URL", API_URL)
    for name in (
        "BOOKSHELF_TOKEN",
        "BOOKSHELF_CLIENT_ID",
        "BOOKSHELF_CLIENT_SECRET",
        "BOOKSHELF_TOKEN_URL",
        "BOOKSHELF_WORKOS_CLIENT_ID",
        "BOOKSHELF_USE_KEYCHAIN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_claim_requires_email() -> None:
    result = runner.invoke(app, ["auth", "login", "--agent", "--claim"])

    assert result.exit_code == 2
    assert "--email" in result.stderr


def test_token_without_credentials_names_the_fix() -> None:
    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "bookshelf auth login" in result.stderr


def test_token_prefers_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_TOKEN", "environment-token")

    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 0
    assert result.stdout == "environment-token\n"


def test_token_prints_the_stored_token() -> None:
    credentials.save_credentials(
        "stored-token",
        api_url=API_URL,
        kind=credentials.CredentialKind.USER,
        subject="reader@example.com",
    )

    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 0
    assert result.stdout == "stored-token\n"


def _mock_out_the_token_endpoint(
    monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport
) -> None:
    """Answer the client the CLI builds for a token exchange, which takes no transport argument."""
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: real_client(transport=transport))


def test_token_refreshes_through_the_provider_and_rewrites_the_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Printing a token and sending a request share one grant, one leeway and one rotation."""
    credentials.save_credentials(
        "stale-token",
        api_url=API_URL,
        kind=credentials.CredentialKind.USER,
        refresh_token="rt-old",
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        subject="reader@example.com",
        organization_id="org_123",
    )
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client_test")
    exchanges: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        exchanges.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(
            200,
            json={"access_token": "fresh-token", "refresh_token": "rt-new", "expires_in": 3600},
        )

    _mock_out_the_token_endpoint(monkeypatch, httpx.MockTransport(handler))

    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 0
    assert result.stdout == "fresh-token\n"
    assert exchanges[0]["grant_type"] == "refresh_token"
    assert exchanges[0]["refresh_token"] == "rt-old"
    record = credentials.load_credentials(API_URL)
    assert record is not None
    assert record.access_token == "fresh-token"
    assert record.refresh_token == "rt-new"
    assert record.subject == "reader@example.com"
    assert record.organization_id == "org_123"


def test_token_mints_client_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_CLIENT_ID", "cid")
    monkeypatch.setenv("BOOKSHELF_CLIENT_SECRET", "secret")
    monkeypatch.setenv("BOOKSHELF_TOKEN_URL", "https://issuer.test/token")
    exchanges: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        exchanges.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"access_token": "minted-token", "expires_in": 3600})

    _mock_out_the_token_endpoint(monkeypatch, httpx.MockTransport(handler))

    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 0
    assert result.stdout == "minted-token\n"
    assert exchanges[0]["grant_type"] == "client_credentials"


def test_token_without_a_token_url_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_CLIENT_ID", "cid")
    monkeypatch.setenv("BOOKSHELF_CLIENT_SECRET", "secret")

    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "BOOKSHELF_TOKEN_URL" in result.stderr


def test_token_without_a_workos_client_id_is_a_credential_error() -> None:
    """A stored login that cannot be refreshed exits 3, not as an unexpected failure."""
    credentials.save_credentials(
        "stale-token",
        api_url=API_URL,
        kind=credentials.CredentialKind.USER,
        refresh_token="rt-old",
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
    )

    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "BOOKSHELF_WORKOS_CLIENT_ID" in result.stderr


def test_token_reports_a_spent_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials.save_credentials(
        "stale-token",
        api_url=API_URL,
        kind=credentials.CredentialKind.USER,
        refresh_token="rt-spent",
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client_test")
    transport = httpx.MockTransport(
        lambda _: httpx.Response(400, json={"error_description": "Refresh token already exchanged"})
    )
    _mock_out_the_token_endpoint(monkeypatch, transport)

    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "Refresh token already exchanged" in result.stderr
    assert "bookshelf auth login" in result.stderr


def test_whoami_offline_reports_anonymous() -> None:
    result = runner.invoke(app, ["auth", "whoami", "--offline", "--json"])

    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["source"] == "none"
    assert report["kind"] == "anonymous"
    assert report["reaches"] == "public"


def test_whoami_offline_reports_stored_identity() -> None:
    credentials.save_credentials(
        "stored-token",
        api_url=API_URL,
        kind=credentials.CredentialKind.USER,
        subject="reader@example.com",
        organization_id="org_123",
    )

    result = runner.invoke(app, ["auth", "whoami", "--offline", "--json"])

    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["source"] == "stored_login"
    assert report["kind"] == "user"
    assert report["id"] == "reader@example.com"
    assert report["organization_id"] == "org_123"


def test_whoami_offline_reports_environment_shadowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials.save_credentials(
        "stored-token",
        api_url=API_URL,
        kind=credentials.CredentialKind.USER,
        subject="reader@example.com",
    )
    monkeypatch.setenv("BOOKSHELF_TOKEN", "environment-token")

    result = runner.invoke(app, ["auth", "whoami", "--offline", "--json"])

    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["source"] == "env_token"
    assert report["shadows"] == {
        "source": "stored_login",
        "id": "reader@example.com",
    }
    assert "$BOOKSHELF_TOKEN overrides your stored login" in result.stderr


def test_logout_without_credentials_succeeds() -> None:
    result = runner.invoke(app, ["auth", "logout"])

    assert result.exit_code == 0
    assert "Not logged in" in result.stderr


def test_logout_clears_state_when_revocation_fails() -> None:
    credentials.save_credentials(
        "bsat_dead",
        api_url=API_URL,
        kind=credentials.CredentialKind.AGENT,
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        identity_assertion="assertion",
        subject="agent:dead",
        claimed=True,
    )

    result = runner.invoke(app, ["auth", "logout"])

    assert result.exit_code == 6
    assert "revocation failed" in result.stderr.lower()
    assert credentials.list_credentials() == []


def test_switch_to_unknown_identity_names_list_command() -> None:
    result = runner.invoke(app, ["auth", "switch", "missing@example.com"])

    assert result.exit_code == 2
    assert "bookshelf auth list" in result.stderr


def _store_a_keychain_only_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """Log in with the keychain on, then turn it off, as an upgrade does."""
    monkeypatch.setenv("BOOKSHELF_USE_KEYCHAIN", "1")
    credentials.save_credentials("at", api_url=API_URL, refresh_token="rt")
    monkeypatch.delenv("BOOKSHELF_USE_KEYCHAIN", raising=False)
    assert credentials.load_credentials(API_URL) is None


def test_logout_clears_a_secret_left_in_the_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """The record no longer loads, so logout has to clear it without one to work from."""
    _store_a_keychain_only_record(monkeypatch)

    result = runner.invoke(app, ["auth", "logout"])

    assert result.exit_code == 0
    assert "Cleared credentials" in result.output
    monkeypatch.setenv("BOOKSHELF_USE_KEYCHAIN", "1")
    assert credentials.load_credentials(API_URL) is None


def test_logout_without_any_record_still_reports_not_logged_in() -> None:
    result = runner.invoke(app, ["auth", "logout"])

    assert result.exit_code == 0
    assert "Not logged in" in result.output


def test_whoami_explains_a_record_it_cannot_read(monkeypatch: pytest.MonkeyPatch) -> None:
    _store_a_keychain_only_record(monkeypatch)

    result = runner.invoke(app, ["auth", "whoami", "--offline"])

    assert result.exit_code == 0
    assert "no secret in the credentials file" in result.output
    assert "BOOKSHELF_USE_KEYCHAIN=1" in result.output


def test_list_explains_a_record_it_cannot_read(monkeypatch: pytest.MonkeyPatch) -> None:
    _store_a_keychain_only_record(monkeypatch)

    result = runner.invoke(app, ["auth", "list"])

    assert result.exit_code == 0
    assert "no secret in the credentials file" in result.output


def test_whoami_stays_quiet_when_the_file_holds_the_secret() -> None:
    credentials.save_credentials("at", api_url=API_URL)

    result = runner.invoke(app, ["auth", "whoami", "--offline"])

    assert result.exit_code == 0
    assert "no secret in the credentials file" not in result.output
