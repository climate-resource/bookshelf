"""Fetch, verify, cache and register the resources a version declares.

A recipe states each upstream input once, under ``resources:``.
:func:`resolve_resource` turns one declared name into local bytes and a catalogued pointer,
so a build file reads an input with ``build.use("raw")`` and nothing else.

The ``uri`` and ``path`` forms differ only in how the bytes and the digest are obtained.
Both end in the same registration.

A ``bookshelf://`` reference ends somewhere else.
The platform already holds that resource, so the resolver looks it up rather than registering it,
and the pointer it returns is the resource itself.
This is what makes a book that is built from another book cite the original rather than a copy.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

import httpx

from bookshelf._core.errors import BookshelfError, NotFoundError
from bookshelf._generated import models
from bookshelf._produce.types import HasTrackingId
from bookshelf.cache import ContentCache
from bookshelf.publisher.recipe import ResourceSpec
from bookshelf.publisher.reference import BookshelfReference

DOWNLOAD_TIMEOUT = 600.0
_CHUNK_BYTES = 1 << 20


class RegisterExternal(Protocol):
    """The one registration call a resolved resource makes.

    Both the live and the recording sinks satisfy this,
    so the resolver stays ignorant of where the pointer lands.
    """

    def __call__(
        self,
        *,
        type: models.ResourceType,
        uri: str,
        hash: str,
        metadata: Mapping[str, Any] | None,
    ) -> HasTrackingId:
        """Catalogue an external pointer and return its handle."""
        ...


class PublishedEntry(Protocol):
    """One entry of a published book, as a reference resolves to it."""

    tracking_id: UUID

    @property
    def metadata(self) -> models.ResourceRead:
        """The platform's projection of the resource, which is where its digest comes from."""
        ...

    @property
    def type(self) -> models.ResourceType:
        """The type the platform registered the resource under."""
        ...

    def as_path(self) -> Path:
        """Stream and verify the bytes, returning the cached local path."""
        ...


class PublishedBook(Protocol):
    """One published book, indexed by entry name."""

    @property
    def entry_names(self) -> tuple[str, ...]:
        """The names this book indexes."""
        ...

    def __getitem__(self, name_in_book: str) -> PublishedEntry: ...


class LookupBook(Protocol):
    """The one read a ``bookshelf://`` reference makes.

    The consuming facade satisfies this, so the resolver holds no client of its own.
    """

    def __call__(self, volume: str, version: str, *, edition: int | None = None) -> PublishedBook:
        """Resolve a published book, defaulting to the newest edition."""
        ...


@dataclass(slots=True)
class ResolvedResource:
    """A resolved resource

    This contains a local file with bytes that are ready to read, and the pointer that catalogued them.

    This is deliberately not frozen.
    ``HasTrackingId`` declares a settable ``tracking_id``,
    so freezing it would stop ``used=[raw]`` type checking in a build file.
    """

    name: str
    """The key the resource was declared under, for example ``"raw"``."""
    path: Path
    """The local file holding the bytes, ready for ``pd.read_csv(raw.path)``."""
    hash: str
    """The canonical ``sha256:<hex>`` of the bytes."""
    pointer: HasTrackingId
    """The registered pointer handle."""
    tracking_id: UUID
    """The pointer's id, so the handle passes straight into ``used=`` on a later registration."""


def resolve_resource(
    name: str,
    *,
    resources: Mapping[str, ResourceSpec],
    doi: str | None,
    recipe_dir: Path | None,
    cache: ContentCache,
    register_external: RegisterExternal,
    lookup_book: LookupBook | None = None,
) -> ResolvedResource:
    """Resolve one declared resource into local bytes and a pointer.

    A ``uri`` resource is fetched through ``cache`` and verified against its declared digest.
    A ``path`` resource is read from beside the recipe and its digest is computed.
    Both are then catalogued with ``register_external``.

    A ``bookshelf://`` resource is looked up with ``lookup_book`` instead.
    Nothing is registered for it, because the platform already holds it,
    and the pointer returned is the published resource itself.

    Raises :class:`~bookshelf._core.errors.BookshelfError` naming the declared resources
    when the version does not declare ``name``.
    """
    spec = resources.get(name)
    if spec is None:
        raise BookshelfError(
            f"the version declares no resource {name!r}. {_available_resources(resources)}"
        )
    reference = spec.reference
    if reference is not None:
        return _referenced(name, reference=reference, declared=spec.type, lookup_book=lookup_book)
    if spec.type is None:
        raise BookshelfError(f"resource {name!r} states no type")
    if spec.path is not None:
        # A checked-in file has no remote location, so the pointer records where it sits
        # in the feedstock rather than a URI the platform could resolve.
        uri = spec.path.as_posix()
        path, content_hash = _checked_in(name, relative=spec.path, recipe_dir=recipe_dir)
    elif spec.uri is not None and spec.sha256 is not None:
        uri = spec.uri
        path, content_hash = _fetched(name, uri=spec.uri, sha256=spec.sha256, cache=cache)
    else:
        raise BookshelfError(
            f"resource {name!r} declares a uri without the sha256 it is checked against"
        )
    pointer = register_external(
        type=spec.type,
        uri=uri,
        hash=content_hash,
        metadata={"doi": doi} if doi is not None else None,
    )
    return ResolvedResource(
        name=name,
        path=path,
        hash=content_hash,
        pointer=pointer,
        tracking_id=pointer.tracking_id,
    )


def _referenced(
    name: str,
    *,
    reference: BookshelfReference,
    declared: models.ResourceType | None,
    lookup_book: LookupBook | None,
) -> ResolvedResource:
    """Resolve one ``bookshelf://`` reference into the published resource it names.

    The bytes come down through the consuming cache, which verifies them against the digest
    the platform states, so nothing here hashes anything itself.

    A stated ``type`` is checked rather than trusted.
    A recipe may name a type that the resource does not have,
    and reading the wrong shape is a failure worth catching before the build starts.
    """
    if lookup_book is None:
        raise BookshelfError(
            f"resource {name!r} names {reference.uri}, "
            "but this build resolves no bookshelf references"
        )
    try:
        book = lookup_book(reference.volume, reference.version, edition=reference.edition)
    except NotFoundError as exc:
        raise BookshelfError(
            f"resource {name!r} names {reference.uri}, which is not published: {exc}"
        ) from exc
    name_in_book = reference.name_in_book
    if name_in_book is None:
        entries = book.entry_names
        if len(entries) != 1:
            listed = ", ".join(repr(entry) for entry in entries) or "none"
            raise BookshelfError(
                f"resource {name!r} names the book {reference.uri} rather than an entry of it, "
                f"and that book holds {len(entries)} entries: {listed}. "
                f"Name one, as {reference.uri}/<entry>"
            )
        name_in_book = entries[0]
    try:
        entry = book[name_in_book]
    except KeyError as exc:
        raise BookshelfError(f"resource {name!r} names {reference.uri}, and {exc}") from exc
    if declared is not None and entry.type != declared:
        raise BookshelfError(
            f"resource {name!r} declares type {declared.value}, "
            f"but {reference.uri} is {entry.type.value}. "
            "Correct the type, or leave it out and take the platform's"
        )
    return ResolvedResource(
        name=name,
        path=entry.as_path(),
        hash=entry.metadata.hash,
        pointer=entry,
        tracking_id=entry.tracking_id,
    )


def _available_resources(resources: Mapping[str, ResourceSpec]) -> str:
    """Name the resources a caller can choose between, or say there are none."""
    if not resources:
        return "The version declares no resources. Add one under 'resources:'."
    listed = ", ".join(repr(key) for key in resources)
    return f"The version declares {listed}."


def _download_client() -> httpx.Client:
    """Build the client a fetch uses. Tests rebind this to serve canned bytes."""
    return httpx.Client(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT)


def _fetched(name: str, *, uri: str, sha256: str, cache: ContentCache) -> tuple[Path, str]:
    """Return the local path of a ``uri`` resource, downloading only on a cache miss.

    The declared digest is the cache key, so a hit touches no network at all.
    A download that does not hash to the declared digest is a hard failure with no retry,
    because the upstream file changed or the transfer corrupted, and both need a human.
    Raising inside the staging context keeps the mismatched bytes out of the cache.
    """
    declared = f"sha256:{sha256}"
    cached = cache.get(declared)
    if cached is not None:
        return cached, declared
    digest = hashlib.sha256()
    with cache.stage(declared) as staging:
        with _download_client() as client, client.stream("GET", uri) as response:
            response.raise_for_status()
            with staging.open("wb") as file:
                for chunk in response.iter_bytes(_CHUNK_BYTES):
                    digest.update(chunk)
                    file.write(chunk)
        actual = f"sha256:{digest.hexdigest()}"
        if actual != declared:
            cache.discard(declared)
            raise BookshelfError(
                f"resource {name!r} at {uri} does not match its declared digest. "
                f"Expected {declared}, got {actual}. "
                "The upstream file changed or the transfer corrupted, "
                "so check the resource before restating sha256"
            )
    committed = cache.get(declared)
    if committed is None:
        raise BookshelfError(f"the cache evicted resource {name!r} as it was stored")
    return committed, declared


def _checked_in(name: str, *, relative: Path, recipe_dir: Path | None) -> tuple[Path, str]:
    """Return the path and computed digest of a resource checked in beside the recipe.

    The path is relative to the recipe file, never to the working directory,
    so a build resolves the same file wherever it is run from.
    """
    if recipe_dir is None:
        raise BookshelfError(
            f"resource {name!r} names a checked-in file, "
            "but the recording states no recipe directory"
        )
    base = recipe_dir.resolve()
    resolved = (base / relative).resolve()
    if not resolved.is_relative_to(base):
        raise BookshelfError(f"resource {name!r} resolves outside the recipe directory: {resolved}")
    if not resolved.is_file():
        raise BookshelfError(f"resource {name!r} names a file that does not exist: {resolved}")
    digest = hashlib.sha256()
    with resolved.open("rb") as file:
        for chunk in iter(lambda: file.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return resolved, f"sha256:{digest.hexdigest()}"


__all__ = [
    "DOWNLOAD_TIMEOUT",
    "LookupBook",
    "PublishedBook",
    "PublishedEntry",
    "ResolvedResource",
    "resolve_resource",
]
