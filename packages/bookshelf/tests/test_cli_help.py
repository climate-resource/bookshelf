"""Every command's help renders."""

from typing import Any

import pytest
import typer
from typer.testing import CliRunner

import bookshelf
from bookshelf._cli import app

runner = CliRunner()


def _command_paths(command: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    paths = [prefix]
    for name, sub in getattr(command, "commands", {}).items():
        paths.extend(_command_paths(sub, (*prefix, name)))
    return paths


@pytest.mark.parametrize(
    "path", _command_paths(typer.main.get_command(app)), ids=lambda path: " ".join(path) or "root"
)
def test_help_renders(path: tuple[str, ...]) -> None:
    result = runner.invoke(app, [*path, "--help"])

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["auth", "--help"],
        ["show", "--help"],
        ["show"],
        ["bogus"],
        ["search", "--limit", "0"],
    ],
    ids=lambda args: " ".join(args),
)
def test_help_and_usage_errors_are_plain_text(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    """Nothing branches on a TTY, so a forced terminal must not add colour or panels."""
    monkeypatch.setenv("FORCE_COLOR", "1")

    result = runner.invoke(app, args, color=True)

    assert "\x1b[" not in result.output
    assert "╭" not in result.output


def test_version_prints_the_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"bookshelf {bookshelf.__version__}"
