"""``bookshelf`` command line interface.

A machine-first CLI over the SDK's public operations.
Payload goes to stdout and diagnostics to stderr in every command,
nothing branches on whether a terminal is attached,
and the exit code carries the meaning (see :mod:`bookshelf._cli._runtime`).
"""

import typer

from bookshelf._cli.auth import auth_app
from bookshelf._cli.cache import cache_app
from bookshelf._cli.discovery import search, show

app = typer.Typer(help="Bookshelf data platform CLI.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")
app.add_typer(cache_app, name="cache")
app.command("search")(search)
app.command("show")(show)


def main() -> None:  # pragma: no cover - thin entry point
    app()


__all__ = ["app", "main"]
