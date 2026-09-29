"""Every command's help renders."""

from typing import Any

import pytest
import typer
from typer.testing import CliRunner

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
