"""``bookshelf`` command line interface.

A machine-first CLI over the Bookshelf API.
Payload goes to stdout and diagnostics to stderr in every command,
and the exit code carries the meaning (see :mod:`bookshelf._cli._runtime`).
"""

import typer

from bookshelf import __version__
from bookshelf._cli._runtime import command_group, emit, set_api_url
from bookshelf._cli.auth import auth_app
from bookshelf._cli.cache import cache_app
from bookshelf._cli.discovery import search, show
from bookshelf._cli.preview import preview_app
from bookshelf._cli.producer import discard, publish, record, validate
from bookshelf._cli.uploads import upload
from bookshelf._cli.volume import volume_app

app = command_group("Bookshelf data platform CLI.")


def _print_version(value: bool) -> None:
    if value:
        emit(f"bookshelf {__version__}")
        raise typer.Exit


@app.callback()
def main_options(
    api_url: str | None = typer.Option(
        None, "--api-url", help="Deployment to act against. Defaults to $BOOKSHELF_URL."
    ),
    _version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version,
        is_eager=True,
        help="Print the installed version and exit.",
    ),
) -> None:
    """Options every command shares, read before the subcommand runs."""
    set_api_url(api_url)


app.add_typer(auth_app, name="auth")
app.add_typer(cache_app, name="cache")
app.add_typer(preview_app, name="preview")
app.add_typer(volume_app, name="volume")
app.command("search")(search)
app.command("show")(show)
app.command("record")(record)
app.command("validate")(validate)
app.command("publish")(publish)
app.command("discard")(discard)
app.command("upload")(upload)


def main() -> None:  # pragma: no cover - thin entry point
    app()


__all__ = ["app", "main"]
