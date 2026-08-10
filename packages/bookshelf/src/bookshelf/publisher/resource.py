"""Fetch, verify, cache and register the resources a version declares.

A recipe states each upstream input once, under ``resources:``.
:func:`resolve_resource` turns one declared name into local bytes and a catalogued pointer,
so a build file reads an input with ``bs.use("raw")`` and nothing else.

The ``uri`` and ``path`` forms differ only in how the bytes and the digest are obtained.
Both end in the same registration.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

import httpx

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.types import HasTrackingId
from bookshelf.cache import ContentCache
from bookshelf.publisher.recipe import ResourceSpec

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
) -> ResolvedResource:
    """Resolve one declared resource into local bytes and a registered pointer.

    A ``uri`` resource is fetched through ``cache`` and verified against its declared digest.
    A ``path`` resource is read from beside the recipe and its digest is computed.

    Raises :class:`~bookshelf._core.errors.BookshelfError` naming the declared resources
    when the version does not declare ``name``.
    """
    spec = resources.get(name)
    if spec is None:
        raise BookshelfError(
            f"the version declares no resource {name!r}. {_available_resources(resources)}"
        )
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


__all__ = ["DOWNLOAD_TIMEOUT", "ResolvedResource", "resolve_resource"]
