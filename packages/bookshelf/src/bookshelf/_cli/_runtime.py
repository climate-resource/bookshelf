"""Shared CLI plumbing: exit codes, the output contract, and error mapping.

The callers are scripts and agents, so:

- payload goes to stdout (:func:`emit`), diagnostics to stderr (:func:`note`)
- the exit code carries the meaning (the ``EXIT_*`` table)
- error text names the command that fixes the problem
"""

import json
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import typer

from bookshelf._consume.presentation import human_bytes
from bookshelf._core import errors

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_AUTH_REQUIRED = 3
EXIT_FORBIDDEN = 4
EXIT_NOT_FOUND = 5
EXIT_NETWORK = 6
EXIT_INVALID_BUNDLE = 7


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


def _label(key: str) -> str:
    """Turn a payload key into its display label."""
    if key.endswith("_bytes"):
        key = key.removesuffix("_bytes")
    elif key.startswith("bytes_"):
        key = key.removeprefix("bytes_")
    return key.replace("_", " ").capitalize()


def _is_bytes(key: str) -> bool:
    return key == "bytes" or key.endswith("_bytes") or key.startswith("bytes_")


def _scalar(key: str, value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int) and _is_bytes(key):
        return human_bytes(value)
    return str(value)


def _rows(document: Mapping[str, Any]) -> Generator[str]:
    """Yield one aligned row per entry, indenting whatever nests under it.

    Each mapping aligns to its own widest label, so a nested block reads as its own column.
    """
    width = max((len(_label(key)) for key in document), default=0)
    for key, value in document.items():
        label = _label(key)
        nested = [value] if isinstance(value, Mapping) else value
        if isinstance(nested, list) and any(isinstance(item, Mapping) for item in nested):
            yield label
            for item in nested:
                yield from (f"  {line}" for line in _rows(item))
        elif isinstance(value, list):
            yield f"{label:<{width}} {', '.join(str(item) for item in value) or '-'}"
        else:
            yield f"{label:<{width}} {_scalar(key, value)}"


def emit_document(document: Mapping[str, Any]) -> None:
    """Write the payload to stdout as aligned rows, keyed by the same names ``--json`` uses.

    One renderer over the JSON document, so the two outputs can never drift apart.
    """
    emit("\n".join(_rows(document)))


def emit_payload(document: Mapping[str, Any], *, json_output: bool) -> None:
    """Write one payload, as a JSON document or as aligned rows."""
    if json_output:
        emit_json(document)
    else:
        emit_document(document)


def iso(moment: datetime | None) -> str | None:
    """Render a datetime as UTC ISO-8601 with a ``Z`` suffix."""
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
    "EXIT_INVALID_BUNDLE",
    "EXIT_NETWORK",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_UNEXPECTED",
    "EXIT_USAGE",
    "CliError",
    "command_errors",
    "emit",
    "emit_document",
    "emit_json",
    "emit_payload",
    "field",
    "human_bytes",
    "iso",
    "note",
]
