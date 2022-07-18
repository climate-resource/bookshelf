import os
import re
import tempfile

from click.testing import CliRunner

from bookshelf.cli import main
from bookshelf.shelf import BookShelf


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


def test_save(mocker):
    mock_run = mocker.patch("bookshelf.notebook.run_notebook")
    mock_save = mocker.patch.object(BookShelf, "save", autospec=True)

    runner = CliRunner()
    result = runner.invoke(main, ["save", "example"])
    assert result.exit_code == 0

    assert "Building Book in isolated environment"

    mock_run.assert_called_once()
    mock_save.assert_called_once()
