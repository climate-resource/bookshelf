"""CLI tests for ``bookshelf auth`` against the live in-process app.

Every test drives the Typer app the way a caller does:
argv in, exit code, stdout and stderr out.
The agent flows are served by the real agent-auth service,
WorkOS is faked one module below the CLI exactly as the backend's fake provider expects.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._cli import auth as cli_auth
from bookshelf._core import credentials, oauth
from tests.conftest import CLI_ORG_ID, CLI_USER_EMAIL, FAKE_WORKOS_TOKEN

runner = CliRunner()


def _fake_browser_flow(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    token_data: dict[str, Any] = {
        "access_token": FAKE_WORKOS_TOKEN,
        "refresh_token": "rt-1",
        "expires_in": 3600,
        **overrides,
    }

    def fake_flow(api_url: str = "", *, on_auth_url: Any = None, **_kw: Any) -> dict[str, Any]:
        if on_auth_url is not None:
            on_auth_url("https://auth.test/authorize?x=1")
        return token_data

    monkeypatch.setattr(oauth, "authorization_code_flow", fake_flow)


def _approve_claim(server: str, registration: Any, *, email: str = CLI_USER_EMAIL) -> None:
    """Complete the ceremony the way the signed-in human does, via the claim page's API."""
    query = parse_qs(urlparse(registration.claim.verification_uri).query)
    response = httpx.post(
        f"{server}/agent/identity/claim/verify",
        json={
            "claim_attempt_token": query["claim_attempt_token"][0],
            "user_code": registration.claim.user_code,
        },
        headers={"Authorization": f"Bearer {FAKE_WORKOS_TOKEN}"},
        timeout=10.0,
    )
    response.raise_for_status()


def test_login_saves_user_credentials_and_whoami_reports_them(
    cli_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_browser_flow(monkeypatch)
    result = runner.invoke(app, ["auth", "login"])
    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert f"Logged in as {CLI_USER_EMAIL}" in result.stderr

    stored = credentials.load_credentials(cli_env)
    assert stored is not None
    assert stored.kind == "user"
    assert stored.access_token == FAKE_WORKOS_TOKEN
    assert stored.refresh_token == "rt-1"
    assert stored.subject == CLI_USER_EMAIL

    result = runner.invoke(app, ["auth", "whoami", "--json"])
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["source"] == "stored_login"
    assert report["kind"] == "user"
    assert report["id"] == CLI_USER_EMAIL
    assert report["organization_id"] == CLI_ORG_ID
    assert report["shadows"] is None


def test_login_no_browser_uses_the_device_flow(
    cli_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow = oauth.DeviceFlowInfo(
        user_code="WDJB-MJHT",
        verification_uri="https://auth.test/device",
        verification_uri_complete="https://auth.test/device?user_code=WDJB-MJHT",
        device_code="dev-1",
        interval=0,
        expires_in=300,
    )
    monkeypatch.setattr(oauth, "start_device_flow", lambda **_kw: flow)
    monkeypatch.setattr(
        oauth,
        "poll_device_flow",
        lambda *_a, **_kw: {"access_token": FAKE_WORKOS_TOKEN, "expires_in": 3600},
    )
    result = runner.invoke(app, ["auth", "login", "--no-browser"])
    assert result.exit_code == 0, result.stderr
    assert "WDJB-MJHT" in result.stderr
    assert credentials.load_credentials(cli_env) is not None


def test_agent_login_is_anonymous_and_instant(cli_env: str) -> None:
    result = runner.invoke(app, ["auth", "login", "--agent", "--json"])
    assert result.exit_code == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["kind"] == "agent"
    assert document["claimed"] is False
    assert document["reaches"] == "public"
    assert document["identity_assertion"]
    assert document["assertion_expires_at"] is not None
    assert "Reaches" in result.stderr

    stored = credentials.load_credentials(cli_env)
    assert stored is not None
    assert stored.kind == "agent"
    assert stored.claimed is False
    assert stored.access_token.startswith("bsat_")
    assert stored.identity_assertion is not None
    assert stored.assertion_expires_at is not None
    assert stored.assertion_expires_at != stored.expires_at

    result = runner.invoke(app, ["auth", "whoami", "--json"])
    report = json.loads(result.stdout)
    assert report["kind"] == "agent"
    assert report["claimed"] is False
    assert report["reaches"] == "public"
    assert report["permissions"] == ["bookshelf:read"]


def test_agent_claim_binds_the_identity_to_the_approving_user(
    cli_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli_auth, "_claim_started", lambda registration: _approve_claim(cli_env, registration)
    )
    result = runner.invoke(
        app, ["auth", "login", "--agent", "--claim", "--email", CLI_USER_EMAIL, "--json"]
    )
    assert result.exit_code == 0, result.stderr
    assert "Enter code" in result.stderr
    assert f"Claimed by {CLI_USER_EMAIL}" in result.stderr
    document = json.loads(result.stdout)
    assert document["claimed"] is True
    assert document["organization_id"] == CLI_ORG_ID

    stored = credentials.load_credentials(cli_env)
    assert stored is not None
    assert stored.claimed is True
    assert stored.organization_id == CLI_ORG_ID

    result = runner.invoke(app, ["auth", "whoami", "--json"])
    report = json.loads(result.stdout)
    assert report["kind"] == "agent"
    assert report["claimed"] is True
    assert "bookshelf:write" in report["permissions"]


def test_agent_claim_rejects_a_mismatched_approver(
    cli_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The signed-in fake user is cli@test.com, so approving another email must fail."""
    approvals: list[int] = []

    def approve_with_wrong_account(registration: Any) -> None:
        try:
            _approve_claim(cli_env, registration)
        except httpx.HTTPStatusError as exc:
            approvals.append(exc.response.status_code)

    clock = iter(range(0, 100_000, 700))
    monkeypatch.setattr(cli_auth, "_claim_started", approve_with_wrong_account)
    monkeypatch.setattr(cli_auth, "_sleep", lambda _s: None)
    monkeypatch.setattr(cli_auth, "_monotonic", lambda: float(next(clock)))
    result = runner.invoke(
        app, ["auth", "login", "--agent", "--claim", "--email", "other@test.com"]
    )
    assert approvals == [403]
    assert result.exit_code == 3
    assert "expired" in result.stderr
    assert credentials.load_credentials(cli_env) is None


def test_claim_requires_email(cli_env: str) -> None:
    result = runner.invoke(app, ["auth", "login", "--agent", "--claim"])
    assert result.exit_code == 2
    assert "--email" in result.stderr


def test_token_prints_the_stored_token_and_nothing_else(
    cli_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_browser_flow(monkeypatch)
    assert runner.invoke(app, ["auth", "login"]).exit_code == 0
    result = runner.invoke(app, ["auth", "token"])
    assert result.exit_code == 0
    assert result.stdout == f"{FAKE_WORKOS_TOKEN}\n"


def test_token_with_no_credential_exits_3_and_names_the_fix(cli_env: str) -> None:
    result = runner.invoke(app, ["auth", "token"])
    assert result.exit_code == 3
    assert result.stdout == ""
    assert "bookshelf auth login" in result.stderr


def test_token_prefers_the_environment_token(cli_env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_browser_flow(monkeypatch)
    assert runner.invoke(app, ["auth", "login"]).exit_code == 0
    monkeypatch.setenv("BOOKSHELF_TOKEN", "env-tok")
    result = runner.invoke(app, ["auth", "token"])
    assert result.exit_code == 0
    assert result.stdout == "env-tok\n"


def test_token_refreshes_an_expired_agent_token_from_the_stored_assertion(
    cli_env: str,
) -> None:
    assert runner.invoke(app, ["auth", "login", "--agent"]).exit_code == 0
    stored = credentials.load_credentials(cli_env)
    assert stored is not None
    # Age the access token so the next print must refresh through jwt-bearer.
    from datetime import UTC, datetime

    credentials.save_credentials(
        stored.access_token,
        api_url=stored.api_url,
        kind="agent",
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        identity_assertion=stored.identity_assertion,
        assertion_expires_at=stored.assertion_expires_at,
        subject=stored.subject,
        claimed=stored.claimed,
    )
    result = runner.invoke(app, ["auth", "token"])
    assert result.exit_code == 0, result.stderr
    fresh = result.stdout.strip()
    assert fresh.startswith("bsat_")
    assert fresh != stored.access_token
    # The refreshed token authenticates against the live server.
    me = httpx.get(f"{cli_env}/auth/me", headers={"Authorization": f"Bearer {fresh}"})
    assert me.status_code == 200


def test_whoami_unauthenticated_succeeds_and_reports_anonymous(cli_env: str) -> None:
    result = runner.invoke(app, ["auth", "whoami", "--json"])
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report == {
        "source": "none",
        "kind": "anonymous",
        "id": None,
        "organization_id": None,
        "permissions": [],
        "expires_at": None,
        "api_url": cli_env,
        "shadows": None,
        "reaches": "public",
    }


def test_whoami_reports_env_token_shadowing_a_stored_login(
    cli_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_browser_flow(monkeypatch)
    assert runner.invoke(app, ["auth", "login"]).exit_code == 0
    monkeypatch.setenv("BOOKSHELF_TOKEN", FAKE_WORKOS_TOKEN)
    result = runner.invoke(app, ["auth", "whoami", "--json"])
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["source"] == "env_token"
    assert report["shadows"] == {"source": "stored_login", "id": CLI_USER_EMAIL}

    human = runner.invoke(app, ["auth", "whoami"])
    assert "$BOOKSHELF_TOKEN overrides your stored login" in human.stderr


def test_whoami_offline_reports_the_stored_record_without_a_server(
    cli_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_browser_flow(monkeypatch)
    monkeypatch.setenv("BOOKSHELF_URL", cli_server)
    assert runner.invoke(app, ["auth", "login"]).exit_code == 0
    # An unreachable deployment must not matter offline.
    monkeypatch.setenv("BOOKSHELF_URL", cli_server)
    result = runner.invoke(app, ["auth", "whoami", "--offline", "--json"])
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["source"] == "stored_login"
    assert report["kind"] == "user"
    assert report["id"] == CLI_USER_EMAIL


def test_whoami_reports_a_rejected_credential_as_exit_3(cli_env: str) -> None:
    credentials.save_credentials("bogus-token", api_url=cli_env, kind="user", subject="x@test.com")
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == 3
    assert "revoked or expired" in result.stderr


def test_logout_revokes_the_agent_token_before_clearing(cli_env: str) -> None:
    assert runner.invoke(app, ["auth", "login", "--agent"]).exit_code == 0
    stored = credentials.load_credentials(cli_env)
    assert stored is not None
    result = runner.invoke(app, ["auth", "logout"])
    assert result.exit_code == 0, result.stderr
    assert "Revoked agent token" in result.stderr
    assert credentials.load_credentials(cli_env) is None
    # The revoked token no longer authenticates.
    me = httpx.get(f"{cli_env}/auth/me", headers={"Authorization": f"Bearer {stored.access_token}"})
    assert me.status_code == 401


def test_logout_when_not_logged_in_is_a_success(cli_env: str) -> None:
    result = runner.invoke(app, ["auth", "logout"])
    assert result.exit_code == 0
    assert "Not logged in" in result.stderr


def test_logout_clears_local_state_even_when_revocation_fails(
    cli_env: str, isolated_credentials: Path
) -> None:
    from datetime import UTC, datetime

    credentials.save_credentials(
        "bsat_dead",
        api_url="http://127.0.0.1:9",  # nothing listens here
        kind="agent",
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        identity_assertion="ia_dead",
        subject="agent:dead",
        claimed=True,
    )
    result = runner.invoke(app, ["auth", "logout", "--api-url", "http://127.0.0.1:9"])
    assert result.exit_code == 6
    assert "revocation failed" in result.stderr.lower()
    assert credentials.list_credentials() == []


def test_human_and_agent_logins_coexist_and_switch_flips_the_active_one(
    cli_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_browser_flow(monkeypatch)
    assert runner.invoke(app, ["auth", "login"]).exit_code == 0
    assert runner.invoke(app, ["auth", "login", "--agent"]).exit_code == 0

    listing = runner.invoke(app, ["auth", "list", "--json"])
    rows = [json.loads(line) for line in listing.stdout.splitlines()]
    assert {row["kind"] for row in rows} == {"user", "agent"}
    active = {row["kind"]: row["active"] for row in rows}
    assert active == {"user": False, "agent": True}

    result = runner.invoke(app, ["auth", "switch", CLI_USER_EMAIL])
    assert result.exit_code == 0, result.stderr
    token = runner.invoke(app, ["auth", "token"])
    assert token.stdout == f"{FAKE_WORKOS_TOKEN}\n"


def test_switch_to_an_unknown_identity_is_a_usage_error(cli_env: str) -> None:
    result = runner.invoke(app, ["auth", "switch", "nobody@test.com"])
    assert result.exit_code == 2
    assert "bookshelf auth list" in result.stderr


def test_credentials_per_deployment_coexist(cli_env: str, cli_server: str) -> None:
    """localhost and 127.0.0.1 reach the same server but are distinct deployments."""
    alias = cli_server.replace("127.0.0.1", "localhost")
    assert runner.invoke(app, ["auth", "login", "--agent"]).exit_code == 0
    assert runner.invoke(app, ["auth", "login", "--agent", "--api-url", alias]).exit_code == 0
    rows = [
        json.loads(line)
        for line in runner.invoke(app, ["auth", "list", "--json"]).stdout.splitlines()
    ]
    assert {row["api_url"] for row in rows} == {cli_env, alias}

    result = runner.invoke(app, ["auth", "logout", "--all"])
    assert result.exit_code == 0, result.stderr
    assert credentials.list_credentials() == []
