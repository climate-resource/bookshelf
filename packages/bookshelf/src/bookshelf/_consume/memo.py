"""Remembered platform answers that rarely or never change once issued.

A resource's hash and type are fixed for its lifetime.
A published edition's identity and entry list are fixed too, unless it is retracted,
so a remembered edition is trusted for a while and then checked with one request.
Records are scoped by server, because ids differ between deployments.
"""

import math
import os
import re
import warnings
from dataclasses import dataclass
from uuid import UUID

from bookshelf._core.client import BookshelfClient
from bookshelf._core.credentials import normalise_api_url
from bookshelf._core.hashing import sha256_hex
from bookshelf._core.names import flatten_to_resource_name
from bookshelf._generated import models
from bookshelf.cache import ContentCache

DEFAULT_BOOK_TTL = 24 * 60 * 60.0
_CONTENT_HASH = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


def book_ttl(value: float) -> float:
    """Return ``value`` as a usable trust window, rejecting anything that is not finite seconds."""
    seconds = float(value)
    if math.isnan(seconds) or math.isinf(seconds) or seconds < 0:
        raise ValueError(
            f"book_ttl must be a finite, non-negative number of seconds, not {value!r}"
        )
    return seconds


def default_book_ttl() -> float:
    """Seconds a remembered book edition is trusted before it is checked again.

    ``$BOOKSHELF_CACHE_BOOK_TTL`` overrides the one day default.
    """
    override = os.environ.get("BOOKSHELF_CACHE_BOOK_TTL")
    if not override:
        return DEFAULT_BOOK_TTL
    try:
        return book_ttl(override)  # type: ignore[arg-type]
    except ValueError:
        warnings.warn(
            f"ignoring BOOKSHELF_CACHE_BOOK_TTL={override!r}, it is not a number of seconds",
            stacklevel=2,
        )
        return DEFAULT_BOOK_TTL


def _scope(client: BookshelfClient) -> str:
    # Readable on disk, with a digest suffix so flattening two URLs onto one name cannot mix them.
    url = normalise_api_url(client.base_url)
    digest = sha256_hex(url.encode()).removeprefix("sha256:")
    return f"{flatten_to_resource_name(url)}-{digest[:8]}"


def _resource_key(client: BookshelfClient, tracking_id: UUID) -> str:
    return f"{_scope(client)}/resources/{tracking_id}"


def _book_key(client: BookshelfClient, volume: str, version: str, edition: int) -> str:
    label = f"{flatten_to_resource_name(version)}_e{edition:03}"
    return f"{_scope(client)}/books/{flatten_to_resource_name(volume)}/{label}"


def remembered_resource(
    cache: ContentCache, client: BookshelfClient, tracking_id: UUID
) -> tuple[str, models.ResourceType] | None:
    """Return the remembered ``(hash, type)`` of a resource, if any."""
    record = cache.metadata.get(_resource_key(client, tracking_id))
    if record is None:
        return None
    try:
        content_hash, resource_type = record["hash"], models.ResourceType(record["type"])
    except (KeyError, ValueError):
        return None
    if not isinstance(content_hash, str) or not _CONTENT_HASH.match(content_hash):
        return None
    return content_hash, resource_type


def remember_resource(
    cache: ContentCache, client: BookshelfClient, metadata: models.ResourceRead
) -> None:
    """Remember the immutable parts of a resource record."""
    cache.metadata.put(
        _resource_key(client, metadata.tracking_id),
        {"hash": metadata.hash, "type": metadata.type.value},
    )


@dataclass(frozen=True, slots=True)
class RememberedBook:
    """A pinned edition as last resolved, and whether that is old enough to check again."""

    book: models.BookListItem
    entries: list[models.BookEntryItem]
    stale: bool


def remembered_book(
    cache: ContentCache,
    client: BookshelfClient,
    volume: str,
    version: str,
    edition: int,
    *,
    ttl: float,
) -> RememberedBook | None:
    """Return a remembered pinned edition and its entries, if any."""
    key = _book_key(client, volume, version, edition)
    record = cache.metadata.get(key)
    age = cache.metadata.age(key)
    if record is None or age is None:
        return None
    try:
        book = models.BookListItem.model_validate(record["book"])
        entries = [models.BookEntryItem.model_validate(item) for item in record["entries"]]
    except (KeyError, TypeError, ValueError):
        return None
    # Flattening the path is lossy, so the record itself has to name the edition asked for.
    if (book.volume_name, book.version, book.edition) != (volume, version, edition):
        return None
    return RememberedBook(book, entries, stale=age > ttl)


def confirm_book(
    cache: ContentCache, client: BookshelfClient, volume: str, version: str, edition: int
) -> None:
    """Restart the trust window of a remembered edition the platform still publishes."""
    cache.metadata.touch(_book_key(client, volume, version, edition))


def forget_book(
    cache: ContentCache, client: BookshelfClient, volume: str, version: str, edition: int
) -> None:
    """Drop a remembered edition that the platform no longer publishes."""
    cache.metadata.discard(_book_key(client, volume, version, edition))


def remember_book(
    cache: ContentCache,
    client: BookshelfClient,
    volume: str,
    version: str,
    book: models.BookListItem,
    entries: list[models.BookEntryItem],
) -> None:
    """Remember a resolved pinned edition and its entries."""
    cache.metadata.put(
        _book_key(client, volume, version, book.edition),
        {
            "book": book.model_dump(mode="json"),
            "entries": [entry.model_dump(mode="json") for entry in entries],
        },
    )


__all__ = [
    "DEFAULT_BOOK_TTL",
    "RememberedBook",
    "book_ttl",
    "confirm_book",
    "default_book_ttl",
    "forget_book",
    "remember_book",
    "remember_resource",
    "remembered_book",
    "remembered_resource",
]
