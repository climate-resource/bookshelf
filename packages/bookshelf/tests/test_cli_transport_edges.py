"""How the CLI reports a deployment that answers with something other than the API."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner, Result

from bookshelf._cli import app
from bookshelf._core import credentials
from bookshelf._core.client import BookshelfClient
from tests import _core_payloads as payloads

API_URL = "https://bookshelf.test"
runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credentials, "credentials_path", lambda: tmp_path / "credentials.json")
    monkeypatch.setenv("BOOKSHELF_URL", API_URL)
    for name in (
        "BOOKSHELF_API_URL",
        "BOOKSHELF_TOKEN",
        "BOOKSHELF_AUTH",
        "BOOKSHELF_CLIENT_ID",
        "BOOKSHELF_CLIENT_SECRET",
        "BOOKSHELF_TOKEN_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def _route(monkeypatch: pytest.MonkeyPatch, handler: Handler, *, ambient: bool = False) -> None:
    def build(url: str) -> BookshelfClient:
        transport = httpx.MockTransport(handler)
        if ambient:
            return BookshelfClient(url, transport=transport)
        return BookshelfClient(url, auth=None, transport=transport)

    monkeypatch.setattr("bookshelf._cli.discovery.BookshelfClient", build)


def _stderr(result: Result) -> str:
    return _ANSI.sub("", result.stderr)


def test_an_spa_fallback_is_a_gateway_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _route(
        monkeypatch,
        lambda _request: httpx.Response(
            200, text="<!doctype html><html>spa</html>", headers={"content-type": "text/html"}
        ),
    )

    result = runner.invoke(app, ["show", "example"])

    stderr = _stderr(result)
    assert result.exit_code == 6, stderr
    assert isinstance(result.exception, SystemExit)
    assert "HTTP 200" in stderr
    assert "text/html" in stderr
    assert f"{API_URL}/v1/volumes/example" in stderr
    assert "Traceback" not in stderr
    assert "<" not in stderr


@pytest.mark.parametrize(
    ("args", "named"),
    [
        (["--api-url", "https://bookshelf.test?x=1"], "--api-url"),
        (["--api-url", "https://user:pw@bookshelf.test"], "--api-url"),
        ([], "$BOOKSHELF_URL"),
    ],
)
def test_a_bad_url_is_a_usage_error_naming_its_source(
    monkeypatch: pytest.MonkeyPatch, args: list[str], named: str
) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", "https://bookshelf.test#frag")

    result = runner.invoke(app, [*args, "search"])

    stderr = _stderr(result)
    assert result.exit_code == 2, stderr
    assert f"Error: {named} " in stderr
    assert "pw" not in stderr


def test_a_doubled_api_version_is_a_usage_error_with_a_hint() -> None:
    result = runner.invoke(app, ["--api-url", f"{API_URL}/v1", "search"])

    stderr = _stderr(result)
    assert result.exit_code == 2, stderr
    assert "without the trailing /v1" in stderr


def test_a_spent_login_is_reported_as_one_clean_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """The degradation notice reaches stderr as a diagnostic, never as a Python warning."""
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client_test")
    credentials.default_store().save_login(
        credentials.StoredCredentials(
            access_token="stale",
            api_url=API_URL,
            refresh_token="rt",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
            subject="reader@example.com",
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                400, text="<!doctype html><html>nope</html>", headers={"content-type": "text/html"}
            )
        return httpx.Response(200, json={**payloads.BOOK_LIST, "items": [payloads.VOLUME]})

    _route(monkeypatch, handler, ambient=True)

    result = runner.invoke(app, ["search", "--json"])

    stderr = _stderr(result)
    assert result.exit_code == 0, stderr
    assert "Warning: The stored Bookshelf login could not be refreshed" in stderr
    assert "bookshelf auth login" in stderr
    assert "HTTP 400 Bad Request with a text/html body" in stderr
    assert "UserWarning" not in stderr
    assert "<" not in stderr
