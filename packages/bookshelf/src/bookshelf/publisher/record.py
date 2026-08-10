"""Driver that executes a standalone build file into a reviewable bundle."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from bookshelf._core.config import UNSET, AuthInput
from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.books import DraftBook
from bookshelf._produce.helpers import uuid7
from bookshelf.facade import Bookshelf
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.notebook import ExecutedNotebook, execute_python_build
from bookshelf.publisher.recipe import (
    RecordRecipe,
    ResolvedBook,
    load_record_recipe,
    resolve_book_visibility,
)
from bookshelf.publisher.recording import RecordedDraftBook, RecordingBookshelf


@dataclass(slots=True)
class _RecordingContext:
    recipe: RecordRecipe
    resolved: ResolvedBook
    bundle: Bundle
    bookshelf: RecordingBookshelf | None = None
    book: RecordedDraftBook | None = None
    setup_called: bool = False


_ACTIVE_RECORDING: ContextVar[_RecordingContext | None] = ContextVar(
    "bookshelf_active_recording",
    default=None,
)


class SetupResult:
    """Pair returned by explicit build setup."""

    def __init__(
        self,
        bs: Bookshelf | RecordingBookshelf,
        book: DraftBook | RecordedDraftBook,
    ) -> None:
        self.bs = bs
        self.book = book

    def __iter__(self) -> Iterator[Any]:
        yield self.bs
        yield self.book

    def __getattr__(self, name: str) -> Any:
        return getattr(self.bs, name)


def setup(
    *,
    version: str | None = None,
    visibility: str | models.Visibility | None = None,
    license: str | None = None,
    collection: str | None = None,
    base_url: str | None = None,
    auth: AuthInput = UNSET,
) -> SetupResult:
    """Construct live or recording handles for a standalone build file.

    Under an active recording the version comes from ``bookshelf record --version``,
    so a build file names no version and the two can never disagree.
    Passing one that contradicts the recorder is an error rather than an override.
    ``visibility`` and ``license`` likewise fall back to the recipe when omitted,
    so a recorded build declares its framing in ``bookshelf.yaml`` rather than in the build file.
    :func:`~bookshelf.publisher.recipe.resolve_book_visibility` states the tier that resolves,
    and the default it then imposes on every resource the build records.

    Direct use has no recipe, so ``version`` is required,
    an omitted visibility is ``hidden`` and an omitted licence stays unset.
    """
    book: DraftBook | RecordedDraftBook
    context = _ACTIVE_RECORDING.get()
    if context is not None:
        if context.setup_called:
            raise BookshelfError("a recorded build must call bookshelf.setup once")
        if collection is not None and collection != context.recipe.volume.name:
            raise BookshelfError(
                f"build collection {collection!r} does not match recipe volume "
                f"{context.recipe.volume.name!r}"
            )
        if version is not None and version != context.resolved.version:
            raise BookshelfError(
                f"build version {version!r} does not match the recorded version "
                f"{context.resolved.version!r}. "
                "Drop version= from the build file, because 'bookshelf record --version' states it"
            )
        context.bookshelf = RecordingBookshelf(
            context.bundle,
            base_url,
            auth=auth,
            authors=context.resolved.authors,
        )
        book = context.bookshelf.draft_book(
            collection or context.recipe.volume.name,
            version=context.resolved.version,
            visibility=resolve_book_visibility(visibility, resolved=context.resolved),
            license=license or context.resolved.license,
        )
        if not isinstance(book, RecordedDraftBook):
            raise TypeError("recording sink returned a live draft book")
        context.book = book
        context.setup_called = True
        return SetupResult(context.bookshelf, book)
    if version is None:
        raise BookshelfError(
            "bookshelf.setup found no active recording, and no version was passed. "
            "The recorder takes the version from 'bookshelf record --version'. "
            "Pass version= to build against the API directly instead."
        )
    if collection is None:
        raise BookshelfError(
            "bookshelf.setup found no active recording, and no collection was passed. "
            "A build file is executed by the recorder, which reads the collection from "
            "the recipe, so run it with bookshelf.publisher.run_record. "
            "Pass collection= to build against the API directly instead."
        )
    bs = Bookshelf(base_url, auth=auth)
    book = bs.draft_book(
        collection,
        version=version,
        visibility=visibility if visibility is not None else models.Visibility.hidden,
        license=license,
    )
    return SetupResult(bs, book)


def run_record(
    *,
    build_path: Path | None,
    recipe_path: Path,
    bundle_path: Path,
    version: str,
    parameters: Mapping[str, Any] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Execute a standalone Jupytext build file into a reviewable bundle.

    ``version`` selects the version from the recipe, and it is the only place a version is stated.
    It reaches the build through the recording context rather than through ``parameters``,
    so a build file cannot shadow it with a top-level assignment.
    """
    workdir = cwd or Path.cwd()
    recipe = load_record_recipe(recipe_path)
    resolved = recipe.resolve(version)
    selected = build_path or recipe.build.notebook
    if selected is None:
        raise BookshelfError("pass a build file or set notebook under 'build:' in bookshelf.yaml")
    build = selected if selected.is_absolute() else workdir / selected
    build = build.resolve()
    if build.suffix.lower() != ".py":
        raise BookshelfError("record requires a standalone Jupytext .py build file")
    if not build.is_file():
        raise BookshelfError(f"build file not found: {build}")

    target = bundle_path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{target.name}-record-",
        dir=target.parent,
    ) as staging_dir:
        bundle = Bundle(Path(staging_dir))
        context = _RecordingContext(recipe=recipe, resolved=resolved, bundle=bundle)
        token = _ACTIVE_RECORDING.set(context)
        try:
            with tempfile.TemporaryDirectory(prefix="bookshelf-executed-") as artifacts:
                executed = execute_python_build(
                    build,
                    params=dict(parameters or {}),
                    workdir=workdir,
                    artifacts_dir=Path(artifacts),
                )
                if not context.setup_called:
                    raise BookshelfError("build file must call bookshelf.setup explicitly")
                _record_executed_documents(context, executed)
        finally:
            _ACTIVE_RECORDING.reset(token)
            if context.bookshelf is not None:
                context.bookshelf.close()
        bundle.write()
        _replace_bundle(Path(staging_dir), target)
    return {
        "bundle_path": str(target),
        "manifest_path": str(target / bundle.manifest_path.name),
        "resources": len(bundle.manifest.resources),
        "book_entries": len(bundle.manifest.book.entries) if bundle.manifest.book else 0,
        "published": bool(bundle.manifest.book and bundle.manifest.book.published),
    }


# The kinds stamped on the two evidence documents every recorded book carries.
DOCUMENT_KINDS = ("notebook", "notebook-html")


def _record_executed_documents(
    context: _RecordingContext,
    executed: ExecutedNotebook,
) -> None:
    """Record executed notebook evidence and attach it to the drafted book."""
    if context.bookshelf is None or context.book is None:
        raise BookshelfError("build file must call bookshelf.setup explicitly")
    notebook_kind, html_kind = DOCUMENT_KINDS
    documents = [
        (executed.ipynb_path, f"{executed.name}.ipynb", notebook_kind),
        (executed.html_path, f"{executed.name}.html", html_kind),
    ]
    for path, name_in_book, kind in documents:
        resource = context.bookshelf.recording_sink.record_document(
            path.read_bytes(),
            logical_key=f"document/{name_in_book}",
            metadata={"kind": kind, "notebook_name": executed.name},
        )
        context.book.attach(resource, name_in_book=name_in_book, data_dictionary=[])


def _replace_bundle(staging: Path, target: Path) -> None:
    """Install a completed bundle without exposing partial recording output."""
    if not target.exists():
        staging.rename(target)
        return
    backup = target.with_name(f".{target.name}-backup-{uuid7()}")
    target.rename(backup)
    try:
        staging.rename(target)
    except BaseException:
        backup.rename(target)
        raise
    shutil.rmtree(backup)


def parse_parameters(values: Sequence[str]) -> dict[str, Any]:
    """Parse command-line key and value pairs as YAML scalars."""
    parsed: dict[str, Any] = {}
    for value in values:
        key, separator, raw = value.partition("=")
        if not separator or not key:
            raise BookshelfError(f"invalid parameter {value!r}, expected key=value")
        parsed[key] = yaml.safe_load(raw)
    return parsed


__all__ = [
    "SetupResult",
    "parse_parameters",
    "run_record",
    "setup",
]
