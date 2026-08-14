"""``bookshelf record``, ``bookshelf validate``, ``bookshelf publish`` and ``bookshelf discard``.

The producer surface over :mod:`bookshelf.publisher`,
so a feedstock and a CI action drive the same implementation
rather than each writing its own Python against the library.

``record`` needs the ``publish`` extra for notebook execution
and guards for it up front.
``validate`` and ``publish`` need nothing beyond the core install,
and ``validate`` opens no socket at all.

``discard`` is the other half of a publish that failed:
a draft edition is allocated before validation runs,
so an abandoned attempt leaves an edition behind until it is deleted.
"""

import importlib.util
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer
import yaml

from bookshelf._cli._address import Address, parse_address
from bookshelf._cli._runtime import (
    EXIT_INVALID_BUNDLE,
    EXIT_NOT_FOUND,
    EXIT_UNEXPECTED,
    EXIT_USAGE,
    CliError,
    command_errors,
    emit,
    emit_json,
    field,
)
from bookshelf._core.client import BookshelfClient
from bookshelf._core.config import resolve_base_url
from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf.facade import Bookshelf
from bookshelf.publisher import (
    Bundle,
    RecordRecipe,
    load_record_recipe,
    parse_parameters,
    publish_bundle,
    run_record,
)
from bookshelf.publisher.bundle import InvalidBundleError
from bookshelf.publisher.recipe import available_versions

_RECORD_REQUIREMENTS = ("nbformat", "nbconvert")
_PAGE_SIZE = 100
_MAX_PAGES = 1000


def _require_publish_extra() -> None:
    """Refuse to record when the notebook capture dependencies are absent.

    ``find_spec`` rather than an import,
    so a broken dependency of the renderer surfaces as itself
    rather than as a missing extra.
    """
    missing = [name for name in _RECORD_REQUIREMENTS if importlib.util.find_spec(name) is None]
    if missing:
        raise CliError(
            f"record needs {' and '.join(missing)}, which the publish extra provides. "
            "Run 'uv sync --extra publish', or install 'bookshelf[publish]'.",
            exit_code=EXIT_USAGE,
        )


def _parameters(values: list[str]) -> dict[str, Any]:
    """Parse ``-p KEY=VALUE`` pairs, treating a malformed pair as a usage error.

    ``parse_parameters`` raises the base ``BookshelfError``,
    which maps to the unexpected-failure code.
    A caller's typo is not an unexpected failure.
    """
    try:
        return parse_parameters(values)
    except BookshelfError as exc:
        raise CliError(str(exc), exit_code=EXIT_USAGE) from exc


def _load_recipe(path: Path) -> RecordRecipe:
    """Load the record recipe, treating an unreadable or malformed one as a usage error."""
    try:
        return load_record_recipe(path)
    except (OSError, yaml.YAMLError, BookshelfError) as exc:
        raise CliError(
            f"cannot read the recipe at {path}: {exc}. "
            "Run 'bookshelf record --recipe PATH' to point at a different one.",
            exit_code=EXIT_USAGE,
        ) from exc


def _resolve_version(version: str | None, loaded: RecordRecipe) -> str:
    """Resolve which version to build, naming the ones the recipe declares either way.

    ``--version`` is required rather than defaulted,
    because a default in the recipe would be a second place a version is stated.
    Both the omitted case and the unknown case list the versions,
    so the message is the answer rather than a prompt to go and read the recipe.
    """
    if version is None:
        raise CliError(
            f"record needs --version naming the version to build. "
            f"{available_versions(loaded.versions)}",
            exit_code=EXIT_USAGE,
        )
    try:
        loaded.resolve(version)
    except BookshelfError as exc:
        raise CliError(str(exc), exit_code=EXIT_USAGE) from exc
    return version


def _resolve_build(build: Path | None, loaded: RecordRecipe, recipe: Path) -> Path:
    """Resolve which build file to execute, naming the fix for each caller mistake.

    ``run_record`` repeats these checks and raises the base ``BookshelfError`` for them,
    which the exit table maps to an unexpected failure.
    A caller's typo is not an unexpected failure,
    so the resolution happens here and ``run_record`` receives a path it has already accepted.
    """
    selected = build or loaded.build.notebook
    if selected is None:
        raise CliError(
            f"no build file given and {recipe} sets no notebook. "
            "Run 'bookshelf record BUILD', or set 'notebook:' under 'build:' in the recipe.",
            exit_code=EXIT_USAGE,
        )

    resolved = (selected if selected.is_absolute() else Path.cwd() / selected).resolve()
    if resolved.suffix.lower() != ".py":
        raise CliError(
            f"record needs a standalone Jupytext .py build file, got {resolved}. "
            "Run 'bookshelf record BUILD' naming the .py file.",
            exit_code=EXIT_USAGE,
        )
    if not resolved.is_file():
        raise CliError(
            f"build file not found: {resolved}. "
            "Run 'bookshelf record BUILD' naming a file that exists.",
            exit_code=EXIT_USAGE,
        )
    return resolved


@contextmanager
def _bundle_errors(root: Path) -> Generator[None]:
    """Map a bundle that refuses itself, and one that will not load, onto the invalid-bundle code.

    A malformed manifest is a distinct outcome from a crash,
    so a caller can branch on it.
    ``ValueError`` covers both the schema-major refusal
    and the pydantic validation failure.
    """
    try:
        yield
    except InvalidBundleError as exc:
        raise CliError(
            f"{exc}. Run 'bookshelf record' to rebuild the bundle.",
            exit_code=EXIT_INVALID_BUNDLE,
        ) from exc
    except (OSError, ValueError) as exc:
        raise CliError(
            f"cannot read a bundle at {root}: {exc}. Run 'bookshelf record' to build one.",
            exit_code=EXIT_INVALID_BUNDLE,
        ) from exc


def _emit_summary(summary: dict[str, Any], labels: dict[str, str], *, json_output: bool) -> None:
    """Emit one summary, as JSON for a machine caller or aligned rows for a human."""
    if json_output:
        emit_json(summary)
        return
    emit("\n".join(field(labels[key], str(summary[key])) for key in labels))


_RECORD_LABELS = {
    "bundle_path": "Bundle",
    "manifest_path": "Manifest",
    "resources": "Resources",
    "book_entries": "Entries",
    "published": "Publishes",
}

_VALIDATE_LABELS = {
    "bundle_path": "Bundle",
    "resources": "Resources",
    "book_entries": "Entries",
    "published": "Publishes",
}

_PUBLISH_LABELS = {
    "outcome": "Outcome",
    "volume": "Volume",
    "version": "Version",
    "edition": "Edition",
    "resources": "Resources",
    "dedupe_hits": "Dedupe hits",
    "converged": "Converged",
}


def record(
    build: Path | None = typer.Argument(
        None,
        help="Standalone Jupytext build file. Defaults to the recipe's notebook.",
    ),
    recipe: Path = typer.Option(
        Path("bookshelf.yaml"), "--recipe", help="Sectioned Bookshelf recipe."
    ),
    bundle: Path = typer.Option(Path("bundle"), "--bundle", help="Bundle directory to write."),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Required. Version to build, naming a book under 'books:' in the recipe.",
    ),
    parameter: list[str] = typer.Option(
        [],
        "--parameter",
        "-p",
        metavar="KEY=VALUE",
        help="Build parameter, read as a YAML scalar. Repeatable.",
    ),
    force: bool = typer.Option(False, "--force", help="Replace an existing bundle directory."),
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Execute a build file and record it into a reviewable bundle."""
    with command_errors():
        _require_publish_extra()
        if bundle.exists() and not force:
            raise CliError(
                f"{bundle} already exists. "
                f"Run 'bookshelf record --force --bundle {bundle}' to replace it.",
                exit_code=EXIT_USAGE,
            )
        # Load the recipe here, even when BUILD is given.
        # run_record loads it either way, so a malformed one must fail here rather than there.
        loaded = _load_recipe(recipe)
        selected = _resolve_version(version, loaded)
        resolved_build = _resolve_build(build, loaded, recipe)
        summary = run_record(
            build_path=resolved_build,
            recipe_path=recipe,
            bundle_path=bundle,
            version=selected,
            parameters=_parameters(parameter),
        )
        _emit_summary(summary, _RECORD_LABELS, json_output=json_output)


def validate(
    bundle: Path = typer.Argument(Path("bundle"), help="Bundle directory to validate."),
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Assert a recorded bundle is a replayable published book."""
    with command_errors():
        with _bundle_errors(bundle):
            loaded = Bundle.read_validated(bundle)
            framing = loaded.require_framing()
        summary = {
            "bundle_path": str(bundle),
            "resources": len(loaded.manifest.resources),
            "book_entries": len(framing.entries),
            "published": framing.published,
        }
        _emit_summary(summary, _VALIDATE_LABELS, json_output=json_output)


def publish(
    bundle: Path = typer.Argument(Path("bundle"), help="Bundle directory to replay."),
    api_url: str | None = typer.Option(None, "--api-url", help="Deployment to publish to."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report what would be sent without sending it. Resolves no edition.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Replay a recorded bundle to publish it, converging on one edition."""
    # Credentials resolve through the usual chain, so there is no token flag
    # to leave a secret in a process list or a CI log.
    with command_errors():
        # Publishing asks only for the framing,
        # because a bundle recorded as a draft replays as a draft.
        with _bundle_errors(bundle):
            loaded = Bundle.read(bundle)
            framing = loaded.require_framing()

        with Bookshelf(resolve_base_url(api_url)) as client:
            outcome = publish_bundle(loaded, client, dry_run=dry_run)

        summary = {
            "outcome": outcome.kind,
            "volume": framing.volume,
            "version": framing.version,
            "edition": outcome.edition,
            "resources": outcome.resource_count,
            "dedupe_hits": outcome.dedupe_hits,
            "converged": outcome.converged,
        }
        _emit_summary(summary, _PUBLISH_LABELS, json_output=json_output)


def discard(
    address: str = typer.Argument(help="Draft edition to discard, as volume@version_eNNN."),
    api_url: str | None = typer.Option(None, "--api-url", help="Deployment to discard in."),
    json_output: bool = typer.Option(False, "--json", help="Emit the outcome as JSON."),
) -> None:
    """Delete a draft edition, so a publish that failed validation leaves no debris.

    Only a draft can be discarded.
    A published book is protected by the API, and the CLI refuses one before it asks.
    """
    with command_errors():
        parsed = parse_address(address)
        if parsed.entry is not None:
            raise CliError(
                f"discard takes a book, not a file within one, and {address!r} names a file. "
                f"Run 'bookshelf discard {parsed.volume}@{parsed.version}_eNNN'.",
                exit_code=EXIT_USAGE,
            )
        if parsed.version is None or parsed.edition is None:
            raise CliError(
                f"discard needs an exact edition, and {address!r} does not name one. "
                f"Run 'bookshelf show {parsed.volume}' to see the editions, then "
                f"'bookshelf discard {parsed.volume}@VERSION_eNNN'.",
                exit_code=EXIT_USAGE,
            )
        with BookshelfClient(resolve_base_url(api_url)) as client:
            book = _resolve_draft(client, parsed)
            client.delete_book(book.id)
        if json_output:
            emit_json({"outcome": "discarded", "book_id": book.id, "address": str(parsed)})
            return
        emit(field("Discarded", f"{parsed} ({book.id})"))


def _resolve_draft(client: BookshelfClient, parsed: Address) -> models.BookListItem:
    """Resolve an address to the one draft book it names, refusing a published one.

    The listing is paged,
    so an edition past the first page is walked to rather than reported as absent.
    """
    match: models.BookListItem | None = None
    for page in range(_MAX_PAGES):
        books = client.list_books(
            volume=parsed.volume,
            version=parsed.version,
            limit=_PAGE_SIZE,
            offset=page * _PAGE_SIZE,
        )
        match = next((item for item in books.items if item.edition == parsed.edition), None)
        if match is not None or not books.has_more:
            break
    else:
        raise CliError(
            f"{parsed} lookup exceeded the pagination safety cap.",
            exit_code=EXIT_UNEXPECTED,
        )
    if match is None:
        raise CliError(
            f"{parsed} does not resolve to a book. "
            f"Run 'bookshelf show {parsed.volume}' to see what is there.",
            exit_code=EXIT_NOT_FOUND,
        )
    if match.status != models.BookStatus.draft:
        raise CliError(
            f"{parsed} is {match.status}, and only a draft can be discarded. "
            "Publish a corrected edition instead.",
            exit_code=EXIT_USAGE,
        )
    return match


__all__ = ["discard", "publish", "record", "validate"]
