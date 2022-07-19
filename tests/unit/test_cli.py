import logging
import re
import tempfile

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
        result = runner.invoke(main, ["run", "example", "--output", str(td)])
        assert result.exit_code == 0, result.output

        mock_run.assert_called_once_with("example", output_directory=td, force=False)


def test_run_failed(mocker, caplog):
    mock_run = mocker.patch("bookshelf.commands.cmd_run.run_notebook", autospec=True)
    mock_run.side_effect = ValueError("Something went wrong")
    with tempfile.TemporaryDirectory() as td:
        runner = CliRunner()
        result = runner.invoke(main, ["run", "example", "--output", str(td)])
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
    result = runner.invoke(main, ["publish", "example"])
    assert result.exit_code == 0

    assert "Building Book in isolated environment" in caplog.text

    mock_run.assert_called_once()
    mock_publish.assert_called_once()

    assert mock_publish.call_args.args[1] == mock_run.return_value


def test_publish_failed(mocker, caplog):
    mock_run = mocker.patch("bookshelf.commands.cmd_publish.run_notebook")
    mock_run.side_effect = ValueError("Something went wrong")

    runner = CliRunner()
    result = runner.invoke(main, ["publish", "example"])
    assert result.exit_code == 1

    assert "Something went wrong" in caplog.text
    assert "Aborted!" in result.output
