import os
import re
import tempfile

from click.testing import CliRunner

from bookshelf.cli import main


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0

    assert "Usage: bookshelf [OPTIONS] COMMAND [ARGS]" in result.output
    assert "Bookshelf for managing reusable datasets" in result.output

    expected_commands = [r"run\s+Run a notebook"]

    for exp in expected_commands:
        assert re.search(exp, result.output)


def test_run():
    with tempfile.TemporaryDirectory() as td:
        runner = CliRunner()
        result = runner.invoke(main, ["run", "example", "--output", str(td)])
        assert result.exit_code == 0, result.output

        assert sorted(os.listdir(str(td))) == sorted(
            [
                "example",  # output
                "example.ipynb",
                "example.yaml",
                "example.py",
            ]
        )
