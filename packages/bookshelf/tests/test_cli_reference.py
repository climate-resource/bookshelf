"""The command reference in docs/cli.md is generated, so it must match the CLI it describes."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def generator() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "generate_cli_reference.py"
    spec = importlib.util.spec_from_file_location("bookshelf_generate_cli_reference", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_reference_is_current(generator: ModuleType) -> None:
    page = generator.PAGE.read_text()

    assert generator.rewritten(page) == page, "Run 'make cli-reference'."


def test_hidden_commands_and_flags_stay_out_of_the_reference(generator: ModuleType) -> None:
    reference = generator.render()

    assert "bookshelf preview" not in reference
    assert "--install-completion" not in reference
    record = reference.split("### `bookshelf record`", 1)[1].split("###", 1)[0]
    assert "--book" in record
    assert "--version" not in record
