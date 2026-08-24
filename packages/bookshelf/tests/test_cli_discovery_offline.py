"""CLI discovery tests that do not require the private backend."""

import pytest
from typer.testing import CliRunner

from bookshelf._cli import app

API_URL = "http://127.0.0.1:9"
runner = CliRunner()


def test_malformed_address_never_reaches_the_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", API_URL)

    result = runner.invoke(app, ["show", "bad address"])

    assert result.exit_code == 2
    assert "malformed address" in result.stderr


def test_network_failure_uses_the_network_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", API_URL)

    result = runner.invoke(app, ["search"])

    assert result.exit_code == 6
