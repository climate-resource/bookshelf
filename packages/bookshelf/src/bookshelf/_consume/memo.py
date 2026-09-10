"""Remembered platform answers that rarely or never change once issued.

A resource's hash and type are fixed for its lifetime.
A published edition's identity and entry list are fixed too, unless it is retracted,
so a remembered edition is trusted for a while and then checked with one request.
Records are scoped by server, because ids differ between deployments.
"""

import hashlib
import time
from dataclasses import dataclass
from uuid import UUID

from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf.cache import ContentCache


def _scope(client: BookshelfClient) -> str:
    return hashlib.sha256(client.base_url.encode()).hexdigest()[:16]


def _resource_key(client: BookshelfClient, tracking_id: UUID) -> str:
    return f"{_scope(client)}/resources/{tracking_id}"


def _book_key(client: BookshelfClient, volume: str, version: str, edition: int) -> str:
    coordinate = hashlib.sha256(f"{volume}\0{version}\0{edition}".encode()).hexdigest()[:32]
    return f"{_scope(client)}/books/{coordinate}"


def remembered_resource(
    cache: ContentCache, client: BookshelfClient, tracking_id: UUID
) -> tuple[str, models.ResourceType] | None:
    """Return the remembered ``(hash, type)`` of a resource, if any."""
    record = cache.metadata.get(_resource_key(client, tracking_id))
    if record is None:
        return None
    try:
        return str(record["hash"]), models.ResourceType(record["type"])
    except (KeyError, ValueError):
        return None


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
    cache: ContentCache, client: BookshelfClient, volume: str, version: str, edition: int
) -> RememberedBook | None:
    """Return a remembered pinned edition and its entries, if any."""
    record = cache.metadata.get(_book_key(client, volume, version, edition))
    if record is None:
        return None
    try:
        book = models.BookListItem.model_validate(record["book"])
        entries = [models.BookEntryItem.model_validate(item) for item in record["entries"]]
        resolved_at = float(record["resolved_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return RememberedBook(book, entries, stale=time.time() - resolved_at > cache.book_ttl)


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
    """Remember a resolved or freshly checked pinned edition and its entries."""
    cache.metadata.put(
        _book_key(client, volume, version, book.edition),
        {
            "book": book.model_dump(mode="json"),
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "resolved_at": time.time(),
        },
    )


__all__ = [
    "RememberedBook",
    "forget_book",
    "remember_book",
    "remember_resource",
    "remembered_book",
    "remembered_resource",
]
