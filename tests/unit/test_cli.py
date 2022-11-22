import logging
import re
import tempfile

import pytest
from click.testing import CliRunner

from bookshelf.cli import main
from bookshelf.shelf import BookShelf

logging.basicConfig()


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0

    assert "Usage: bookshelf [OPTIONS] COMMAND [ARGS]" in result.output
    assert "Bookshelf for managing reusable datasets" in result.output

    expected_commands = [r"run\s+Run a notebook"]

    for exp in expected_commands:
        assert re.search(exp, result.output)


def test_run(mocker):
    mock_run = mocker.patch("bookshelf.commands.cmd_run.run_notebook", autospec=True)

    with tempfile.TemporaryDirectory() as td:
        runner = CliRunner()
        result = runner.invoke(main, ["run", "examples/simple", "--output", str(td)])
        assert result.exit_code == 0, result.output

        mock_run.assert_called_once_with(
            "examples/simple", output_directory=td, force=False, version="v0.1.0"
        )


@pytest.mark.parametrize(
    "args",
    [
        [],
        [
            "--version",
            "v4.0.0",
            "--version",
            "v5.1.0",
        ],
    ],
)
def test_run_multiple(mocker, args):
    mock_run = mocker.patch("bookshelf.commands.cmd_run.run_notebook", autospec=True)

    with tempfile.TemporaryDirectory() as td:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "run",
                "examples/multiple_versions",
                *args,
                "--output",
                str(td),
            ],
        )
        assert result.exit_code == 0, result.output

        mock_run.assert_has_calls(
            [
                (
                    ("examples/multiple_versions",),
                    dict(
                        output_directory=td,
                        force=False,
                        version="v4.0.0",
                    ),
                ),
                (
                    ("examples/multiple_versions",),
                    dict(
                        output_directory=td,
                        force=False,
                        version="v5.1.0",
                    ),
                ),
            ]
        )


def test_run_failed(mocker, caplog):
    mock_run = mocker.patch("bookshelf.commands.cmd_run.run_notebook", autospec=True)
    mock_run.side_effect = ValueError("Something went wrong")
    with tempfile.TemporaryDirectory() as td:
        runner = CliRunner()
        result = runner.invoke(main, ["run", "examples/simple", "--output", str(td)])
        assert result.exit_code == 1

    assert "Something went wrong" in caplog.text
    assert "Aborted!" in result.output


def test_publish(mocker, caplog):
    mock_run = mocker.patch(
        "bookshelf.commands.cmd_publish.run_notebook", autospec=True
    )
    mock_publish = mocker.patch.object(BookShelf, "publish", autospec=True)

    caplog.set_level("INFO")

    runner = CliRunner()
    result = runner.invoke(main, ["publish", "examples/simple"])
    assert result.exit_code == 0

    assert "Building Book in isolated environment" in caplog.text

    mock_run.assert_called_once()
    mock_publish.assert_called_once()

    assert mock_publish.call_args.args[1] == mock_run.return_value


def test_publish_multiple(mocker, caplog):
    mock_run = mocker.patch(
        "bookshelf.commands.cmd_publish.run_notebook", autospec=True
    )
    mock_publish = mocker.patch.object(BookShelf, "publish", autospec=True)

    runner = CliRunner()
    result = runner.invoke(main, ["publish", "examples/multiple_versions"])

    assert result.exit_code == 0

    assert mock_run.call_count == 2
    assert mock_publish.call_count == 2


def test_publish_failed(mocker, caplog):
    mock_run = mocker.patch("bookshelf.commands.cmd_publish.run_notebook")
    mock_run.side_effect = ValueError("Something went wrong")

    runner = CliRunner()
    result = runner.invoke(main, ["publish", "examples/simple"])
    assert result.exit_code == 1

    assert "Something went wrong" in caplog.text
    assert "Aborted!" in result.output


def test_publish_missing():
    runner = CliRunner()
    result = runner.invoke(main, ["publish", "examples/unknown"])
    assert result.exit_code == 1

    assert result.exc_info[0] == FileNotFoundError
