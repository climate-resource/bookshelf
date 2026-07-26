"""Shared CLI plumbing: exit codes, the output contract, and error mapping.

The callers are scripts and agents, so:

- payload goes to stdout (:func:`emit`), diagnostics to stderr (:func:`note`)
- the exit code carries the meaning (the ``EXIT_*`` table)
- error text names the command that fixes the problem
"""

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import typer

from bookshelf._core import errors

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_AUTH_REQUIRED = 3
EXIT_FORBIDDEN = 4
EXIT_NOT_FOUND = 5
EXIT_NETWORK = 6


class CliError(Exception):
    """A command failure with a specific exit code and a caller-facing message."""

    def __init__(self, message: str, *, exit_code: int = EXIT_UNEXPECTED) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def emit(payload: str) -> None:
    """Write payload to stdout."""
    typer.echo(payload)


def emit_json(document: Any) -> None:
    """Write one JSON document to stdout."""
    typer.echo(json.dumps(document))


def note(message: str) -> None:
    """Write a diagnostic line to stderr."""
    typer.echo(message, err=True)


def field(label: str, value: str) -> str:
    """Render an aligned ``label  value`` row."""
    return f"{label:<13} {value}"


def iso(moment: datetime | None) -> str | None:
    """Render a datetime as UTC ISO-8601 with a ``Z`` suffix."""
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def human_bytes(count: int) -> str:
    """Render a byte count for the human summaries."""
    size = float(count)
    for unit in ("B", "kB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1000
    return f"{int(size)} B"  # pragma: no cover - unreachable


def _exit_code_for(exc: errors.BookshelfError) -> int:
    if isinstance(exc, errors.AuthenticationError):
        return EXIT_AUTH_REQUIRED
    if isinstance(exc, errors.ForbiddenError):
        return EXIT_FORBIDDEN
    if isinstance(exc, errors.NotFoundError):
        return EXIT_NOT_FOUND
    if isinstance(exc, errors.ServerError | errors.TransportError):
        return EXIT_NETWORK
    if isinstance(exc, errors.ValidationError):
        return EXIT_USAGE
    return EXIT_UNEXPECTED


def _remedy_for(exit_code: int) -> str | None:
    if exit_code == EXIT_AUTH_REQUIRED:
        return (
            "Run 'bookshelf auth login' to sign in, or "
            "'bookshelf auth login --agent' to register an agent identity."
        )
    if exit_code == EXIT_FORBIDDEN:
        return (
            "Your credential does not reach this data. "
            "Run 'bookshelf auth login --agent --claim --email you@org.com' "
            "to bind this agent to your organisation."
        )
    return None


@contextmanager
def command_errors() -> Generator[None]:
    """Map SDK errors and :class:`CliError` onto the exit-code table."""
    try:
        yield
    except CliError as exc:
        note(f"Error: {exc}")
        raise typer.Exit(code=exc.exit_code) from exc
    except errors.BookshelfError as exc:
        exit_code = _exit_code_for(exc)
        detail = exc.detail if isinstance(exc, errors.APIError) else str(exc)
        note(f"Error: {detail}")
        remedy = _remedy_for(exit_code)
        if remedy is not None:
            note(remedy)
        raise typer.Exit(code=exit_code) from exc


__all__ = [
    "EXIT_AUTH_REQUIRED",
    "EXIT_FORBIDDEN",
    "EXIT_NETWORK",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_UNEXPECTED",
    "EXIT_USAGE",
    "CliError",
    "command_errors",
    "emit",
    "emit_json",
    "field",
    "human_bytes",
    "iso",
    "note",
]
