"""Driver that executes a standalone build file into a reviewable bundle."""

from __future__ import annotations

import json
import keyword
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from bookshelf._core.config import UNSET, AuthInput
from bookshelf._core.errors import BookshelfError
from bookshelf._core.names import flatten_to_resource_name
from bookshelf._generated import models
from bookshelf._produce import helpers
from bookshelf._produce.books import DraftBook
from bookshelf._produce.facade import nests_discovery
from bookshelf._produce.provenance import derive_code_ref
from bookshelf.facade import Bookshelf
from bookshelf.publisher.bundle import MANIFEST_NAME, Bundle
from bookshelf.publisher.notebook import ExecutedNotebook, assigned_names, execute_python_build
from bookshelf.publisher.recipe import (
    DiscoveryFields,
    RecordRecipe,
    ResolvedBook,
    VolumeSection,
    load_record_recipe,
    resolve_book_visibility,
)
from bookshelf.publisher.recording import RecordedDraftBook, RecordingBookshelf, RecordingError
from bookshelf.publisher.resource import ResolvedResource


class RecordRefusedError(BookshelfError, ValueError):
    """The recorder refused what it was asked to do before running the build."""


@dataclass(slots=True)
class _RecordingContext:
    recipe: RecordRecipe
    resolved: ResolvedBook
    bundle: Bundle
    recipe_dir: Path | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    code_ref: str | None = None
    bookshelf: RecordingBookshelf | None = None
    book: RecordedDraftBook | None = None
    setup_called: bool = False


_ACTIVE_RECORDING: ContextVar[_RecordingContext | None] = ContextVar(
    "bookshelf_active_recording",
    default=None,
)


@dataclass(frozen=True, slots=True)
class Build:
    """One build in progress: the resources the recipe declares, and the book it writes.

    The recipe vocabulary lives here rather than on the facade,
    because it means something only while a recipe is driving the build.
    """

    bs: Bookshelf | RecordingBookshelf
    book: DraftBook | RecordedDraftBook

    def __iter__(self) -> Iterator[Any]:
        """Unpack as ``bs, book``, which is how a build file opens."""
        return iter((self.bs, self.book))

    def use(self, name: str) -> ResolvedResource | dict[str, ResolvedResource]:
        """Fetch, verify, cache and register a resource the recipe declares.

        Only a recorded build can do this.
        A direct build has no recipe, so there is nothing to resolve a name against.
        A ``whole_book: true`` reference returns resolved resources keyed by entry name.
        """
        if not isinstance(self.bs, RecordingBookshelf):
            raise BookshelfError(
                f"build.use({name!r}) found no active recording. "
                "Resources are declared in the recipe, which the recorder reads, "
                "so run the build file with 'bookshelf record'. "
                "Fetch the file and call register_external to build against the API directly."
            )
        return self.bs.use(name)


# These travel through their own dedicated parameters below rather than through this
# mapping, so they are never duplicated between the two.
_CARRIED_SEPARATELY = frozenset({"description", "authors"})


def _resolved_discovery(resolved: ResolvedBook) -> dict[str, Any]:
    """Read the effective discovery values off an already resolved book.

    The fields are walked rather than listed,
    so one added to the recipe later reaches the wire without another edit here.
    """
    return {
        name: value
        for name in DiscoveryFields.model_fields
        if name not in _CARRIED_SEPARATELY
        and nests_discovery(name)
        and (value := getattr(resolved.discovery, name)) is not None
    }


def setup(
    *,
    version: str | None = None,
    visibility: str | models.Visibility | None = None,
    license: str | None = None,
    collection: str | None = None,
    base_url: str | None = None,
    auth: AuthInput = UNSET,
) -> Build:
    """Construct live or recording handles for a standalone build file.

    Under an active recording the version comes from ``bookshelf record --version``,
    so a build file names no version and the two can never disagree.
    Passing one that contradicts the recorder is an error rather than an override.

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
            resolved=context.resolved,
            recipe_dir=context.recipe_dir,
            parameters=context.parameters,
            code_ref=context.code_ref,
        )
        discovery = _resolved_discovery(context.resolved)
        book = context.bookshelf.draft_book(
            collection or context.recipe.volume.name,
            version=context.resolved.version,
            visibility=resolve_book_visibility(visibility, resolved=context.resolved),
            license=license or context.resolved.license,
            description=context.resolved.discovery.description,
            discovery=discovery,
            authors=context.resolved.authors,
        )
        if not isinstance(book, RecordedDraftBook):
            raise TypeError("recording sink returned a live draft book")
        _record_volume(context.bundle, context.recipe.volume)
        context.book = book
        context.setup_called = True
        return Build(context.bookshelf, book)

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
    return Build(bs, book)


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
    _check_parameters(parameters or {}, build=build)

    target = bundle_path.resolve()
    _check_replaceable(
        target,
        protected={
            "the recipe": recipe_path,
            "the build file": build,
            "the working directory": workdir,
        },
    )
    # Read before the staging directory lands in the clone, and before the build can move the cwd.
    code_ref = _code_ref(workdir)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{target.name}-record-",
        dir=target.parent,
    ) as staging_dir:
        bundle = Bundle(Path(staging_dir))
        context = _RecordingContext(
            recipe=recipe,
            resolved=resolved,
            bundle=bundle,
            recipe_dir=recipe_path.resolve().parent,
            parameters=dict(parameters or {}),
            code_ref=code_ref,
        )
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
        _record_processing(bundle)
        bundle.write()
        _replace_bundle(Path(staging_dir), target)
    return {
        "bundle_path": str(target),
        "manifest_path": str(target / bundle.manifest_path.name),
        "resources": len(bundle.manifest.resources),
        "book_entries": len(bundle.manifest.book.entries) if bundle.manifest.book else 0,
        "published": bool(bundle.manifest.book and bundle.manifest.book.published),
    }


def _code_ref(workdir: Path) -> str | None:
    """Derive the code ref up front, leaving a failure for the activity to report if it needs one.

    A build may pass ``code_ref=`` itself, so a checkout without git is not yet an error.
    """
    try:
        return derive_code_ref(workdir)
    except BookshelfError:
        return None


def _check_replaceable(target: Path, *, protected: Mapping[str, Path]) -> None:
    """Refuse a bundle target that replacing would destroy something other than a bundle."""
    if not target.exists():
        return
    if not target.is_dir():
        raise RecordRefusedError(
            f"{target} is not a directory, so it is not a bundle to replace. "
            "Pass --bundle naming a bundle directory or a path that does not exist yet"
        )
    for what, path in protected.items():
        if path.resolve().is_relative_to(target):
            raise RecordRefusedError(
                f"{target} holds {what}, so replacing it would delete the feedstock. "
                "Pass --bundle naming a directory of its own, such as 'bundle'"
            )
    if any(target.iterdir()) and not (target / MANIFEST_NAME).is_file():
        raise RecordRefusedError(
            f"{target} is not a bundle, because it holds no {MANIFEST_NAME}, "
            "so record will not replace it. "
            "Pass --bundle naming a different directory, or remove this one yourself"
        )


def _check_parameters(parameters: Mapping[str, Any], *, build: Path | None = None) -> None:
    """Refuse a parameter the build cannot take or the manifest cannot record, before the build runs."""
    for key, value in parameters.items():
        if (
            not isinstance(key, str)
            or not key.isidentifier()
            or keyword.iskeyword(key)
            or (key.startswith("__") and key.endswith("__"))
        ):
            raise RecordRefusedError(
                f"parameter {key!r} is not a variable a build file can assign. "
                "Name a top-level assignment in the build file"
            )
        try:
            # Encoding is what refuses a lone surrogate, which JSON would otherwise escape.
            dumped = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
            if json.loads(dumped) != value:
                raise ValueError(
                    "JSON would record a different value, such as text for a number key"
                )
        except (TypeError, ValueError) as exc:
            raise RecordRefusedError(
                f"parameter {key!r} cannot be recorded, because the manifest stores parameters "
                f"as JSON ({exc}). Quote a date or any other value as a string"
            ) from exc
    assigned = None if build is None else assigned_names(build)
    if assigned is None:
        return
    unknown = [key for key in parameters if key not in assigned]
    if unknown:
        listed = ", ".join(repr(name) for name in sorted(assigned)) or "nothing"
        raise RecordRefusedError(
            f"parameter {unknown[0]!r} matches no top-level 'name = value' assignment in {build}, "
            f"so it would change nothing. The build assigns {listed}"
        )


def _record_processing(bundle: Bundle) -> None:
    """Stamp the book's processing fingerprint from the activity that generated its members.

    Publishing does not send this, because the replay request carries the activity itself.
    It is recorded so ``bookshelf validate`` reads as a complete account of the build.
    """
    if bundle.manifest.book is None:
        return
    activity = bundle.manifest.activity
    bundle.manifest.book.processing = (
        [] if activity is None else [(activity.code_ref, activity.config_hash)]
    )


def _record_volume(bundle: Bundle, volume: VolumeSection) -> None:
    """Stamp the volume facts the recipe states, and only those, so replay leaves the rest alone."""
    if bundle.manifest.book is None:
        return
    stated = volume.model_dump(mode="json", exclude={"name"}, exclude_unset=True, exclude_none=True)
    bundle.manifest.book.volume_discovery = stated or None


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
    manifest = context.bundle.manifest
    taken = {resource.name for resource in manifest.resources}
    if manifest.book is not None:
        taken.update(entry.name for entry in manifest.book.entries)
    documents = [
        (executed.ipynb_path, f"{executed.name}.ipynb", notebook_kind),
        (executed.html_path, f"{executed.name}.html", html_kind),
    ]
    for path, filename, kind in documents:
        # One name: a replayed resource is registered under the name its book entry takes.
        name = flatten_to_resource_name(filename)
        if name in taken:
            raise RecordingError(
                f"resource name {name!r} is reserved for the executed notebook the recorder attaches. "
                "Rename what the build records under it"
            )
        resource = context.bookshelf.recording_sink.record_document(
            path.read_bytes(),
            name=name,
            metadata={"kind": kind, "notebook_name": executed.name},
        )
        context.book.attach(resource, name_in_book=name, data_dictionary=[])


def _replace_bundle(staging: Path, target: Path) -> None:
    """Install a completed bundle without exposing partial recording output."""
    if not target.exists():
        staging.rename(target)
        return
    backup = target.with_name(f".{target.name}-backup-{helpers.uuid7()}")
    target.rename(backup)
    try:
        staging.rename(target)
    except BaseException:
        backup.rename(target)
        raise
    shutil.rmtree(backup)


def parse_parameters(values: Sequence[str]) -> dict[str, Any]:
    """Parse command-line key and value pairs as YAML scalars.

    Raises :class:`RecordRefusedError` for a pair that does not parse, or a value the manifest cannot record.
    """
    parsed: dict[str, Any] = {}
    for value in values:
        key, separator, raw = value.partition("=")
        if not separator or not key:
            raise RecordRefusedError(f"invalid parameter {value!r}, expected key=value")
        try:
            parsed[key] = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise RecordRefusedError(f"parameter {key!r} is not valid YAML: {exc}") from exc
    _check_parameters(parsed)
    return parsed


__all__ = [
    "Build",
    "RecordRefusedError",
    "parse_parameters",
    "run_record",
    "setup",
]
