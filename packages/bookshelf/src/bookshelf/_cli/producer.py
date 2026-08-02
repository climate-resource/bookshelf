"""``bookshelf record``, ``bookshelf validate`` and ``bookshelf publish``.

The producer surface over :mod:`bookshelf.publisher`,
so a feedstock and a CI action drive the same implementation
rather than each writing its own Python against the library.

``record`` needs the ``publish`` extra for notebook execution
and guards for it up front.
``validate`` and ``publish`` need nothing beyond the core install,
and ``validate`` opens no socket at all.
"""

import importlib.util
from pathlib import Path
from typing import Any

import typer

from bookshelf._cli._runtime import (
    EXIT_INVALID_BUNDLE,
    EXIT_USAGE,
    CliError,
    command_errors,
    emit,
    emit_json,
    field,
)
from bookshelf._core.config import resolve_base_url
from bookshelf._core.errors import BookshelfError
from bookshelf._core.hashing import sha256_hex
from bookshelf.facade import Bookshelf
from bookshelf.publisher import (
    Bundle,
    compute_book_bundle_hash,
    parse_parameters,
    replay_bundle_sync,
    run_record,
)
from bookshelf.publisher.bundle import BundleBook

_RECORD_REQUIREMENTS = ("papermill", "nbconvert")


def _require_publish_extra() -> None:
    """Refuse to record when the notebook execution dependencies are absent.

    ``find_spec`` rather than an import,
    so a broken dependency of papermill surfaces as itself
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


def _read_bundle(root: Path) -> Bundle:
    """Load a bundle directory, mapping an unreadable one onto its own exit code.

    A malformed manifest is a distinct outcome from a crash,
    so a caller can branch on it.
    ``ValueError`` covers both the schema-major refusal
    and the pydantic validation failure.
    """
    try:
        return Bundle.read(root)
    except (OSError, ValueError) as exc:
        raise CliError(
            f"cannot read a bundle at {root}: {exc}. Run 'bookshelf record' to build one.",
            exit_code=EXIT_INVALID_BUNDLE,
        ) from exc


def _invalid(message: str) -> CliError:
    return CliError(
        f"{message}. Run 'bookshelf record' to rebuild the bundle.",
        exit_code=EXIT_INVALID_BUNDLE,
    )


def _require_framing(bundle: Bundle) -> BundleBook:
    """Return the recorded book framing, or fail as an invalid bundle."""
    framing = bundle.manifest.book
    if framing is None:
        raise _invalid("bundle has no book framing")
    return framing


def _check_bundle(bundle: Bundle) -> BundleBook:
    """Assert a bundle is a replayable published book, re-hashing its managed bytes."""
    framing = _require_framing(bundle)
    if not framing.published:
        raise _invalid("bundle does not record a publish operation")
    if not framing.entries:
        raise _invalid("bundle has no book entries")

    resources = {resource.tracking_id for resource in bundle.manifest.resources}
    for entry in framing.entries:
        if entry.tracking_id not in resources:
            raise _invalid(f"book entry {entry.name_in_book!r} has no resource")

    for resource in bundle.manifest.resources:
        if resource.kind != "managed":
            continue
        actual = sha256_hex(bundle.resource_bytes(resource))
        if actual != resource.hash:
            raise _invalid(
                f"resource {resource.tracking_id} has hash {resource.hash}, got {actual}"
            )

    return framing


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
    "bundle_hash": "Bundle hash",
    "resources": "Resources",
    "book_entries": "Entries",
    "published": "Publishes",
}

_PUBLISH_LABELS = {
    "outcome": "Outcome",
    "volume": "Volume",
    "version": "Version",
    "edition": "Edition",
    "bundle_hash": "Bundle hash",
    "resources": "Resources",
}


def record(
    build: Path | None = typer.Argument(
        None,
        help="Standalone Jupytext build file. Defaults to the recipe's notebook.",
    ),
    recipe: Path = typer.Option(Path("bookshelf.yaml"), "--recipe", help="Slim Bookshelf recipe."),
    bundle: Path = typer.Option(Path("bundle"), "--bundle", help="Bundle directory to write."),
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
        summary = run_record(
            build_path=build,
            recipe_path=recipe,
            bundle_path=bundle,
            parameters=_parameters(parameter),
        )
        _emit_summary(summary, _RECORD_LABELS, json_output=json_output)


def validate(
    bundle: Path = typer.Argument(Path("bundle"), help="Bundle directory to validate."),
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Assert a recorded bundle is a replayable published book, and hash it."""
    with command_errors():
        loaded = _read_bundle(bundle)
        framing = _check_bundle(loaded)
        summary = {
            "bundle_path": str(bundle),
            "bundle_hash": compute_book_bundle_hash(loaded.manifest),
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
        help="Resolve the edition and report the outcome without publishing.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Replay a recorded bundle to publish it, converging on one edition."""
    # Credentials resolve through the usual chain, so there is no token flag
    # to leave a secret in a process list or a CI log.
    with command_errors():
        loaded = _read_bundle(bundle)
        framing = _require_framing(loaded)
        bundle_hash = compute_book_bundle_hash(loaded.manifest)

        with Bookshelf(resolve_base_url(api_url)) as client:
            drafted = client.draft_book(
                framing.volume,
                version=framing.version,
                description=framing.description,
                citation_doi=framing.citation_doi,
                license=framing.license,
                visibility=framing.visibility,
                metadata=framing.metadata,
                bundle_hash=bundle_hash,
            )
            # Drafting is the only way to learn whether the edition already exists,
            # and it is keyed on the bundle hash, so a dry run adds no edition of its own.
            if drafted.status == "published":
                outcome, edition, resources = "no-op", drafted.metadata.edition, 0
            elif dry_run:
                outcome = "would-publish"
                edition = drafted.metadata.edition
                resources = len(loaded.manifest.resources)
            else:
                published = replay_bundle_sync(loaded, client)
                outcome = "published"
                edition = published.metadata.edition
                resources = len(loaded.manifest.resources)

        summary = {
            "outcome": outcome,
            "volume": framing.volume,
            "version": framing.version,
            "edition": edition,
            "bundle_hash": bundle_hash,
            "resources": resources,
        }
        _emit_summary(summary, _PUBLISH_LABELS, json_output=json_output)


__all__ = ["publish", "record", "validate"]
