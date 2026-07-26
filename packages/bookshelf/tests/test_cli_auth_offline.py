"""Offline CLI authentication tests that do not require the private backend."""

import json
from datetime import UTC, datetime
from pathlib import Path

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
        kind="user",
        subject="reader@example.com",
    )

    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 0
    assert result.stdout == "stored-token\n"


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
        kind="user",
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
        kind="user",
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
        kind="agent",
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
