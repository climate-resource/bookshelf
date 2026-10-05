"""Shared CLI plumbing: exit codes, the output contract, and error mapping.

The callers are scripts and agents, so:

- payload goes to stdout (:func:`emit`), diagnostics to stderr (:func:`note`)
- the exit code carries the meaning (the ``EXIT_*`` table)
- error text names the command that fixes the problem
"""

import json
import warnings
from collections.abc import Generator, Iterable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import typer

from bookshelf._core import errors
from bookshelf._core.config import resolve_base_url
from bookshelf._core.resolution import LOGIN_REMEDY, CredentialSource, resolve_credential
from bookshelf._produce.provenance import _CodeRefError

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_AUTH_REQUIRED = 3
EXIT_FORBIDDEN = 4
EXIT_NOT_FOUND = 5
EXIT_NETWORK = 6
EXIT_INVALID_BUNDLE = 7
EXIT_CONFLICT = 8
EXIT_CONTRACT = 9

EXIT_CODES: tuple[tuple[int, str], ...] = (
    (EXIT_OK, "success"),
    (EXIT_UNEXPECTED, "any other failure, including a bug worth reporting"),
    (EXIT_USAGE, "usage: bad arguments, a malformed address, or unusable local setup"),
    (EXIT_AUTH_REQUIRED, "no accepted credential: log in, or refresh the one in play"),
    (EXIT_FORBIDDEN, "the credential lacks a permission"),
    (EXIT_NOT_FOUND, "the volume, book, entry or resource does not exist"),
    (EXIT_NETWORK, "network, gateway or server failure, worth retrying"),
    (EXIT_INVALID_BUNDLE, "the bundle is malformed or refused"),
    (EXIT_CONFLICT, "the request conflicts with what the platform holds"),
    (EXIT_CONTRACT, "the server answered outside the API contract: upgrade bookshelf"),
)
"""Every exit code the CLI uses, with its meaning, for help text and the reference page."""


class CliError(Exception):
    """A command failure with a specific exit code and a caller-facing message."""

    def __init__(self, message: str, *, exit_code: int = EXIT_UNEXPECTED) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def exit_code_epilog() -> str:
    """Render the exit code table for the end of ``--help``."""
    rows = "\n".join(f"  {code}  {meaning}" for code, meaning in EXIT_CODES)
    # Click rewraps an epilog paragraph unless it opens with \b.
    return f"Exit codes:\n\n\b\n{rows}"


def command_group(help_text: str, *, epilog: str | None = None) -> typer.Typer:
    """Return a command group whose help, usage errors and tracebacks are the same plain text on a TTY."""
    return typer.Typer(
        help=help_text,
        epilog=epilog,
        no_args_is_help=True,
        rich_markup_mode=None,
        pretty_exceptions_enable=False,
    )


_api_url: str | None = None


def set_api_url(value: str | None) -> None:
    """Record the deployment the top-level ``--api-url`` names, for :func:`base_url`."""
    global _api_url
    _api_url = value


def base_url() -> str:
    """Resolve the deployment to act against, honouring the top-level ``--api-url``."""
    try:
        return resolve_base_url(_api_url, source="--api-url")
    except errors.ConfigurationError as exc:
        # Some commands resolve the URL before entering command_errors.
        note(f"Error: {exc}")
        raise typer.Exit(code=EXIT_USAGE) from exc


def requested_api_url() -> str | None:
    """Return ``--api-url`` as given, for a command that narrows only when it was passed."""
    return _api_url


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


def _byte_count_stem(key: str) -> str | None:
    """Return what a byte-count key is counting, or ``None`` when it counts something else.

    A payload spells a byte count three ways, so the spellings are recognised in one place.
    """
    if key == "bytes":
        return key
    if key.endswith("_bytes"):
        return key.removesuffix("_bytes")
    if key.startswith("bytes_"):
        return key.removeprefix("bytes_")
    return None


def _label(key: str) -> str:
    """Turn a payload key into its display label."""
    return (_byte_count_stem(key) or key).replace("_", " ").capitalize()


def _binary_bytes(count: int) -> str:
    """Render a byte count in binary units, so a cap set in GiB reads back as the same number."""
    if count < 1024:
        return f"{count} B"
    size = float(count)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        size /= 1024
        if size < 1024 or unit == "TiB":
            break
    return f"{size:.1f} {unit}"


def _scalar(key: str, value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int) and _byte_count_stem(key) is not None:
        return _binary_bytes(value)
    return str(value)


def _blocks(value: object) -> list[Mapping[str, Any]] | None:
    """Return the mappings that render as an indented block, or ``None`` for a plain row.

    Every item has to be a mapping, because a mixed list renders as one row and keeps the rest.
    """
    items = [value] if isinstance(value, Mapping) else value
    if isinstance(items, list) and items and all(isinstance(item, Mapping) for item in items):
        return items
    return None


def _rows(document: Mapping[str, Any]) -> Generator[str]:
    """Yield one aligned row per entry, indenting whatever nests under it.

    Each mapping aligns to its own widest label, so a nested block reads as its own column.
    A blank line separates sibling blocks, so one block's last row never reads as the next one's.
    """
    width = max((len(_label(key)) for key in document), default=0)
    for key, value in document.items():
        label = _label(key)
        blocks = _blocks(value)
        if blocks is not None:
            yield label
            for position, block in enumerate(blocks):
                if position:
                    yield ""
                yield from (f"  {line}" for line in _rows(block))
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


def emit_payloads(documents: Iterable[Mapping[str, Any]], *, json_output: bool) -> None:
    """Write a listing: one JSON document per line, or blocks with a blank line between them.

    A block runs to several lines, so without the separator consecutive results read as one.
    """
    for position, document in enumerate(documents):
        if position and not json_output:
            emit("")
        emit_payload(document, json_output=json_output)


def iso(moment: datetime | None) -> str | None:
    """Render a datetime as UTC ISO-8601 to the second, with a ``Z`` suffix."""
    if moment is None:
        return None
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _exit_code_for(exc: errors.BookshelfError) -> int:
    if isinstance(exc, errors.AuthenticationError | errors.AuthenticationRequiredError):
        return EXIT_AUTH_REQUIRED
    if isinstance(exc, errors.ForbiddenError):
        return EXIT_FORBIDDEN
    if isinstance(exc, errors.NotFoundError):
        return EXIT_NOT_FOUND
    if isinstance(
        exc,
        errors.ServerError | errors.TransportError | errors.RateLimitError | errors.GatewayError,
    ):
        return EXIT_NETWORK
    if isinstance(exc, errors.ConflictError):
        return EXIT_CONFLICT
    if isinstance(exc, errors.UnexpectedResponseError | errors.ContractError):
        return EXIT_CONTRACT
    if isinstance(
        exc,
        errors.RequestValidationError
        | errors.ConfigurationError
        | errors.AuthConfigurationError
        | errors.SelectionError
        | _CodeRefError,
    ):
        return EXIT_USAGE
    return EXIT_UNEXPECTED


def _forbidden_remedy() -> str:
    """Pick the 403 remedy for the credential actually in play."""
    described = resolve_credential(base_url()).describe()
    if described.source not in (CredentialSource.STORED_LOGIN, CredentialSource.NONE):
        return f"Ask an organisation admin to grant the required permission to {described.label}."
    return (
        "Ask an organisation admin to grant the required permission, "
        "then run 'bookshelf auth login' again to refresh it."
    )


def _remedy_for(exit_code: int) -> str | None:
    if exit_code == EXIT_AUTH_REQUIRED:
        try:
            return resolve_credential(base_url()).describe().remedy
        except Exception:
            # The remedy is a hint, so failing to resolve one must not mask the error being reported.
            return LOGIN_REMEDY
    if exit_code == EXIT_FORBIDDEN:
        return _forbidden_remedy()
    return None


def _note_warning(message: Warning | str, *_args: object, **_kwargs: object) -> None:
    note(f"Warning: {message}")


@contextmanager
def command_errors() -> Generator[None]:
    """Map SDK errors and :class:`CliError` onto the exit-code table.

    A warning raised inside reaches stderr as one diagnostic line, without Python's source context.
    """
    try:
        with warnings.catch_warnings():
            warnings.showwarning = _note_warning
            yield
    except CliError as exc:
        note(f"Error: {exc}")
        raise typer.Exit(code=exc.exit_code) from exc
    except errors.BookshelfError as exc:
        exit_code = _exit_code_for(exc)
        # Without a problem document the request it failed on is the most useful context.
        if isinstance(exc, errors.APIError) and exc.problem is not None:
            detail = exc.detail
        else:
            detail = str(exc)
        note(f"Error: {detail}")
        remedy = _remedy_for(exit_code)
        if remedy is not None:
            note(remedy)
        raise typer.Exit(code=exit_code) from exc


__all__ = [
    "EXIT_AUTH_REQUIRED",
    "EXIT_CODES",
    "EXIT_CONFLICT",
    "EXIT_CONTRACT",
    "EXIT_FORBIDDEN",
    "EXIT_INVALID_BUNDLE",
    "EXIT_NETWORK",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_UNEXPECTED",
    "EXIT_USAGE",
    "CliError",
    "base_url",
    "command_errors",
    "command_group",
    "exit_code_epilog",
    "emit",
    "emit_json",
    "emit_payload",
    "emit_payloads",
    "field",
    "iso",
    "note",
    "requested_api_url",
    "set_api_url",
]
