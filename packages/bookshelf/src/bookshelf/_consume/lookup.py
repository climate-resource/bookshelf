"""Paged catalogue lookups shared by the facades and the Volume handles.

The platform pages everything, and a volume holds few enough books that a caller
should not have to page through them.
These walk the pages once so both the facade and a Volume resolve a book the same way.
"""

import asyncio
from typing import Any, Literal

from bookshelf._consume.books import AsyncBook, Book
from bookshelf._consume.memo import (
    forget_book,
    remember_book,
    remembered_book,
)
from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import BookshelfError, NotFoundError
from bookshelf._core.names import book_coordinate, version_key
from bookshelf._generated import models
from bookshelf.cache import ContentCache

PAGE_SIZE = 100
MAX_PAGES = 1000

_LOOKUP_CAP = "book lookup exceeded the pagination safety cap"
_ENTRY_CAP = "book entry lookup exceeded the pagination safety cap"


def book_order(item: models.BookListItem) -> tuple[Any, ...]:
    """Order books by version, then edition.

    The CLI resolves ``latest`` with this same key,
    so the two surfaces agree on which book is the newest.
    """
    return (version_key(item.version), item.edition)


def missing_book(volume: str, version: str, edition: int | None) -> NotFoundError:
    return NotFoundError(
        f"no published book {book_coordinate(version, edition)!r} in volume {volume!r}",
        status_code=404,
    )


def _chosen(items: list[models.BookListItem], edition: int | None) -> models.BookListItem | None:
    if edition is None:
        return max(items, key=lambda item: item.edition) if items else None
    return next((item for item in items if item.edition == edition), None)


def all_entries(client: BookshelfClient, book_id: str) -> list[models.BookEntryItem]:
    """Walk every entry a book indexes."""
    entries: list[models.BookEntryItem] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        response = client.list_book_entries(book_id, limit=PAGE_SIZE, cursor=cursor)
        entries.extend(response.items)
        cursor = response.next_cursor
        if cursor is None:
            return entries
    raise BookshelfError(_ENTRY_CAP)


async def all_entries_async(client: BookshelfClient, book_id: str) -> list[models.BookEntryItem]:
    """The asynchronous twin of :func:`all_entries`."""
    entries: list[models.BookEntryItem] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        response = await client.list_book_entries_async(book_id, limit=PAGE_SIZE, cursor=cursor)
        entries.extend(response.items)
        cursor = response.next_cursor
        if cursor is None:
            return entries
    raise BookshelfError(_ENTRY_CAP)


def find_book(
    client: BookshelfClient, volume: str, version: str, edition: int | None
) -> models.BookListItem:
    """Pick the published book a coordinate names, defaulting to the latest edition."""
    if edition is None:
        response = client.list_books(
            volume=volume,
            version=version,
            status="published",
            latest_only=True,
            limit=PAGE_SIZE,
        )
        chosen = _chosen(response.items, None)
    else:
        chosen = None
        for page in range(MAX_PAGES):
            response = client.list_books(
                volume=volume,
                version=version,
                status="published",
                limit=PAGE_SIZE,
                offset=page * PAGE_SIZE,
            )
            chosen = _chosen(response.items, edition)
            if chosen is not None or not response.has_more:
                break
        else:
            raise BookshelfError(_LOOKUP_CAP)
    if chosen is None:
        raise missing_book(volume, version, edition)
    return chosen


async def find_book_async(
    client: BookshelfClient, volume: str, version: str, edition: int | None
) -> models.BookListItem:
    """The asynchronous twin of :func:`find_book`."""
    if edition is None:
        response = await client.list_books_async(
            volume=volume,
            version=version,
            status="published",
            latest_only=True,
            limit=PAGE_SIZE,
        )
        chosen = _chosen(response.items, None)
    else:
        chosen = None
        for page in range(MAX_PAGES):
            response = await client.list_books_async(
                volume=volume,
                version=version,
                status="published",
                limit=PAGE_SIZE,
                offset=page * PAGE_SIZE,
            )
            chosen = _chosen(response.items, edition)
            if chosen is not None or not response.has_more:
                break
        else:
            raise BookshelfError(_LOOKUP_CAP)
    if chosen is None:
        raise missing_book(volume, version, edition)
    return chosen


def _republished(
    client: BookshelfClient, remembered: models.BookListItem
) -> models.BookListItem | Literal[False] | None:
    """Re-read a remembered edition.

    Returns the listing refreshed with what can change after publication,
    ``False`` once the edition is no longer published, or ``None`` when the platform could not say.
    """
    try:
        return _refreshed(remembered, client.get_book(remembered.id))
    except NotFoundError:
        return False
    except BookshelfError:
        return None


async def _republished_async(
    client: BookshelfClient, remembered: models.BookListItem
) -> models.BookListItem | Literal[False] | None:
    """The asynchronous twin of :func:`_republished`."""
    try:
        return _refreshed(remembered, await client.get_book_async(remembered.id))
    except NotFoundError:
        return False
    except BookshelfError:
        return None


def _refreshed(
    remembered: models.BookListItem, live: models.BookResponse
) -> models.BookListItem | Literal[False]:
    if live.status is not models.BookStatus.published:
        return False
    return remembered.model_copy(
        update={
            "status": live.status,
            "visibility": live.visibility,
            "metadata": live.metadata,
            "published_at": live.published_at,
            "tombstoned_at": live.tombstoned_at,
            "tombstone_reason": live.tombstone_reason,
        }
    )


def resolve_book(
    client: BookshelfClient,
    cache: ContentCache,
    volume: str,
    version: str,
    edition: int | None,
    *,
    book_ttl: float,
    refresh: bool = False,
) -> Book:
    """Resolve a published Book and the entries it indexes.

    A pinned edition is remembered on disk, so resolving it again makes no request
    until ``book_ttl`` seconds have passed.
    After that one request checks it is still published and refreshes its metadata and visibility,
    so ``book_ttl=0`` always reads them live.
    ``refresh`` ignores the remembered edition and resolves it and its entries afresh.
    The latest edition is always asked for, because a newer one may have been published.
    """
    if edition is not None and not refresh:
        remembered = remembered_book(cache, client, volume, version, edition, ttl=book_ttl)
        if remembered is not None:
            if not remembered.stale:
                return Book(client, cache, remembered.book, remembered.entries)
            live = _republished(client, remembered.book)
            if live is None:
                return Book(client, cache, remembered.book, remembered.entries)
            if live is False:
                forget_book(cache, client, volume, version, edition)
            else:
                remember_book(cache, client, volume, version, live, remembered.entries)
                return Book(client, cache, live, remembered.entries)
    try:
        chosen = find_book(client, volume, version, edition)
    except NotFoundError:
        if edition is not None:
            forget_book(cache, client, volume, version, edition)
        raise
    entries = all_entries(client, chosen.id)
    if edition is not None:
        remember_book(cache, client, volume, version, chosen, entries)
    return Book(client, cache, chosen, entries)


async def resolve_book_async(
    client: BookshelfClient,
    cache: ContentCache,
    volume: str,
    version: str,
    edition: int | None,
    *,
    book_ttl: float,
    refresh: bool = False,
) -> AsyncBook:
    """The asynchronous twin of :func:`resolve_book`."""
    if edition is not None and not refresh:
        remembered = await asyncio.to_thread(
            remembered_book, cache, client, volume, version, edition, ttl=book_ttl
        )
        if remembered is not None:
            if not remembered.stale:
                return AsyncBook(client, cache, remembered.book, remembered.entries)
            live = await _republished_async(client, remembered.book)
            if live is None:
                return AsyncBook(client, cache, remembered.book, remembered.entries)
            if live is False:
                await asyncio.to_thread(forget_book, cache, client, volume, version, edition)
            else:
                await asyncio.to_thread(
                    remember_book, cache, client, volume, version, live, remembered.entries
                )
                return AsyncBook(client, cache, live, remembered.entries)
    try:
        chosen = await find_book_async(client, volume, version, edition)
    except NotFoundError:
        if edition is not None:
            await asyncio.to_thread(forget_book, cache, client, volume, version, edition)
        raise
    entries = await all_entries_async(client, chosen.id)
    if edition is not None:
        await asyncio.to_thread(remember_book, cache, client, volume, version, chosen, entries)
    return AsyncBook(client, cache, chosen, entries)


__all__ = [
    "book_order",
    "resolve_book",
    "resolve_book_async",
]
