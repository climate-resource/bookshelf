"""Offline CLI authentication tests that do not require the private backend."""

import base64
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._core import credentials
from bookshelf._core.client import BookshelfClient

API_URL = "http://127.0.0.1:9"
runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture(autouse=True)
def isolated_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(credentials, "credentials_path", lambda: path)
    monkeypatch.setenv("BOOKSHELF_URL", API_URL)
    for name in (
        "BOOKSHELF_TOKEN",
        "BOOKSHELF_CLIENT_ID",
        "BOOKSHELF_CLIENT_SECRET",
        "BOOKSHELF_TOKEN_URL",
        "BOOKSHELF_WORKOS_CLIENT_ID",
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
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="stored-token",
            api_url=API_URL,
            kind=credentials.CredentialKind.USER,
            subject="reader@example.com",
        )
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
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="stale-token",
            api_url=API_URL,
            kind=credentials.CredentialKind.USER,
            refresh_token="rt-old",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
            subject="reader@example.com",
            organization_id="org_123",
        )
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
    record = credentials.default_store().load(API_URL)
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
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="stale-token",
            api_url=API_URL,
            kind=credentials.CredentialKind.USER,
            refresh_token="rt-old",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )

    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "BOOKSHELF_WORKOS_CLIENT_ID" in result.stderr


def test_token_reports_a_spent_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="stale-token",
            api_url=API_URL,
            kind=credentials.CredentialKind.USER,
            refresh_token="rt-spent",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
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
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="stored-token",
            api_url=API_URL,
            kind=credentials.CredentialKind.USER,
            subject="reader@example.com",
            organization_id="org_123",
        )
    )

    result = runner.invoke(app, ["auth", "whoami", "--offline", "--json"])

    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["source"] == "stored_login"
    assert report["kind"] == "user"
    assert report["id"] == "reader@example.com"
    assert report["organization_id"] == "org_123"
    assert report["permissions"] is None


def test_whoami_offline_reports_environment_shadowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="stored-token",
            api_url=API_URL,
            kind=credentials.CredentialKind.USER,
            subject="reader@example.com",
        )
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
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="bsat_dead",
            api_url=API_URL,
            kind=credentials.CredentialKind.AGENT,
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
            identity_assertion="assertion",
            subject="agent:dead",
            claimed=True,
        )
    )

    result = runner.invoke(app, ["auth", "logout"])

    assert result.exit_code == 6
    assert "revocation failed" in result.stderr.lower()
    assert credentials.default_store().records() == []


def test_switch_to_unknown_identity_names_list_command() -> None:
    result = runner.invoke(app, ["auth", "switch", "missing@example.com"])

    assert result.exit_code == 2
    assert "bookshelf auth list" in result.stderr


def _store_two_identities() -> None:
    credentials.default_store().save_login(
        credentials.StoredCredentials(access_token="one", api_url=API_URL, subject="a@example.com")
    )
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="two", api_url="http://127.0.0.1:8", subject="b@example.com"
        )
    )


def test_list_separates_the_human_blocks() -> None:
    """One identity reads as one block, so consecutive ones need a blank line between them."""
    _store_two_identities()

    result = runner.invoke(app, ["auth", "list"])

    assert result.exit_code == 0, result.output
    assert "\n\n" in result.stdout


def test_list_json_stays_one_document_per_line() -> None:
    """A blank line would break a reader taking one JSON document per line."""
    _store_two_identities()

    result = runner.invoke(app, ["auth", "list", "--json"])

    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if line]
    assert len(lines) == len(result.stdout.strip().splitlines())
    assert [json.loads(line)["id"] for line in lines] == ["a@example.com", "b@example.com"]


def test_api_url_is_read_from_the_top_level_option() -> None:
    """--api-url sits on the app, so it reaches a command that never declares it."""
    result = runner.invoke(
        app, ["--api-url", "http://127.0.0.1:8", "auth", "whoami", "--offline", "--json"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["api_url"] == "http://127.0.0.1:8"


def test_api_url_after_the_subcommand_is_a_usage_error() -> None:
    """The flag moved ahead of the subcommand at 1.0, so the old position must fail loudly."""
    result = runner.invoke(app, ["auth", "whoami", "--offline", "--api-url", "http://127.0.0.1:8"])

    assert result.exit_code == 2
    # Typer colours the option name, so the styling comes off before the message is read.
    assert "No such option: --api-url" in _ANSI.sub("", result.output)


def test_whoami_names_the_env_token_when_the_server_rejects_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKSHELF_TOKEN", "garbage")
    monkeypatch.setattr(
        "bookshelf._cli.auth.BookshelfClient",
        lambda url, auth: BookshelfClient(
            url,
            auth=auth,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(401, json={"detail": "bad token"})
            ),
        ),
    )

    result = runner.invoke(app, ["auth", "whoami"])

    assert result.exit_code == 3
    assert "$BOOKSHELF_TOKEN" in result.stderr
    assert "auth login" not in result.stderr
    assert "is malformed" in result.stderr
    assert "revoked" not in result.stderr


def _jwt(exp: float) -> str:
    claims = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"h.{claims}.s"


@pytest.mark.parametrize(
    ("token", "reason", "absent"),
    [
        (_jwt(0), "expired at 1970-01-01T00:00:00Z", "malformed"),
        (_jwt(4102444800), "revoked, or issued for another deployment", "malformed"),
        ("bsat_unknown", "revoked, or issued for another deployment", "malformed"),
    ],
)
def test_whoami_says_why_the_server_rejected_a_token(
    monkeypatch: pytest.MonkeyPatch, token: str, reason: str, absent: str
) -> None:
    monkeypatch.setenv("BOOKSHELF_TOKEN", token)
    monkeypatch.setattr(
        "bookshelf._cli.auth.BookshelfClient",
        lambda url, auth: BookshelfClient(
            url,
            auth=auth,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(401, json={"detail": "bad token"})
            ),
        ),
    )

    result = runner.invoke(app, ["auth", "whoami"])

    assert result.exit_code == 3
    assert reason in result.stderr
    assert absent not in result.stderr


def test_list_marks_a_credential_that_can_no_longer_be_renewed() -> None:
    past = datetime(2020, 1, 1, tzinfo=UTC)
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="spent", api_url=API_URL, subject="a@example.com", expires_at=past
        )
    )
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="renewable",
            api_url="http://127.0.0.1:8",
            subject="b@example.com",
            expires_at=past,
            refresh_token="refresh",
        )
    )

    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="refreshing-agent",
            api_url="http://127.0.0.1:7",
            kind=credentials.CredentialKind.AGENT,
            subject="agent:c",
            expires_at=past,
            refresh_token="refresh",
        )
    )

    result = runner.invoke(app, ["auth", "list", "--json"])

    assert result.exit_code == 0, result.output
    rows = {json.loads(line)["id"]: json.loads(line) for line in result.stdout.splitlines()}
    assert {name: row["expired"] for name, row in rows.items()} == {
        "a@example.com": True,
        "b@example.com": True,
        "agent:c": True,
    }
    assert {name: row["needs_login"] for name, row in rows.items()} == {
        "a@example.com": True,
        "b@example.com": False,
        "agent:c": False,
    }


def _store_reader() -> None:
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="stored-token", api_url=API_URL, subject="reader@example.com"
        )
    )


def test_token_json_carries_the_token_and_deployment() -> None:
    _store_reader()

    result = runner.invoke(app, ["auth", "token", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"access_token": "stored-token", "api_url": API_URL}


def test_logout_json_lists_what_was_cleared() -> None:
    _store_reader()

    result = runner.invoke(app, ["auth", "logout", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "cleared": [API_URL],
        "revoked": [],
        "revocation_failed": [],
    }


def test_logout_json_without_credentials_clears_nothing() -> None:
    result = runner.invoke(app, ["auth", "logout", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["cleared"] == []


def test_switch_json_names_the_active_identity() -> None:
    _store_reader()

    result = runner.invoke(app, ["auth", "switch", "reader@example.com", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "kind": "user",
        "id": "reader@example.com",
        "api_url": API_URL,
    }


def test_logout_leaves_a_newer_store_alone() -> None:
    path = credentials.credentials_path()
    newer = json.dumps(
        {
            "version": credentials.STORE_VERSION + 1,
            "records": {
                f"{API_URL}|agent": {
                    "access_token": "bsat_theirs",
                    "api_url": API_URL,
                    "kind": "agent",
                }
            },
            "active": {API_URL: "agent"},
        }
    )
    path.write_text(newer)

    result = runner.invoke(app, ["auth", "logout"])

    assert result.exit_code == 2
    assert "newer bookshelf" in " ".join(result.stderr.split())
    assert "Revoked" not in result.stderr
    assert path.read_text() == newer


def test_token_from_an_expired_newer_store_is_a_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client")
    path = credentials.credentials_path()
    newer = json.dumps(
        {
            "version": credentials.STORE_VERSION + 1,
            "records": {
                f"{API_URL}|user": {
                    "access_token": "theirs",
                    "api_url": API_URL,
                    "kind": "user",
                    "refresh_token": "single-use",
                    "expires_at": "2000-01-01T00:00:00+00:00",
                }
            },
            "active": {API_URL: "user"},
        }
    )
    path.write_text(newer)

    result = runner.invoke(app, ["auth", "token"])

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "newer bookshelf" in " ".join(result.stderr.split())
    assert path.read_text() == newer


def _write_newer_store(*, expires_at: str | None = None, refresh_token: str | None = None) -> str:
    record: dict[str, str] = {"access_token": "theirs", "api_url": API_URL, "kind": "user"}
    if expires_at is not None:
        record["expires_at"] = expires_at
    if refresh_token is not None:
        record["refresh_token"] = refresh_token
    newer = json.dumps(
        {
            "version": credentials.STORE_VERSION + 1,
            "records": {f"{API_URL}|user": record},
            "active": {API_URL: "user"},
        }
    )
    credentials.credentials_path().write_text(newer)
    return newer


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--no-browser"],
        ["--agent"],
        ["--agent", "--claim", "--email", "you@example.com"],
    ],
)
def test_login_against_a_newer_store_exits_before_any_network_call(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    from bookshelf._cli import auth as auth_cli

    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("login reached the network")

    monkeypatch.setattr(auth_cli.session, "login_user", no_network)
    monkeypatch.setattr(auth_cli, "BookshelfClient", no_network)
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client")
    newer = _write_newer_store()

    result = runner.invoke(app, ["auth", "login", *arguments])

    stderr = " ".join(_ANSI.sub("", result.stderr).split())
    assert result.exit_code == 2, result.output
    assert "newer bookshelf" in stderr
    assert "auth login" not in stderr
    assert credentials.credentials_path().read_text() == newer


@pytest.mark.parametrize("arguments", [[], ["--no-browser"]])
def test_login_without_a_workos_client_id_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda *_args, **_kwargs: False)

    result = runner.invoke(app, ["auth", "login", *arguments])

    assert result.exit_code == 2, result.output
    assert "BOOKSHELF_WORKOS_CLIENT_ID" in _ANSI.sub("", result.stderr)


def test_token_from_an_expired_newer_store_suggests_only_what_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client")
    _write_newer_store(expires_at="2000-01-01T00:00:00+00:00", refresh_token="single-use")

    result = runner.invoke(app, ["auth", "token"])

    stderr = " ".join(_ANSI.sub("", result.stderr).split())
    assert result.exit_code == 3
    assert "BOOKSHELF_TOKEN Run" not in stderr
    assert "BOOKSHELF_TOKEN." in stderr
    assert "auth login" not in stderr
    assert "auth logout" not in stderr


def test_list_marks_an_expired_token_in_a_newer_store_as_needing_login() -> None:
    _write_newer_store(expires_at="2000-01-01T00:00:00+00:00", refresh_token="single-use")

    result = runner.invoke(app, ["auth", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["needs_login"] is True
