"""Thin public facades for consuming and producing Bookshelf data."""

from __future__ import annotations

from typing import Self
from uuid import UUID

import httpx

from bookshelf._consume.books import AsyncBook, Book
from bookshelf._consume.integrity import HashMismatchError
from bookshelf._consume.resources import (
    AsyncBookEntry,
    AsyncResource,
    BookEntry,
    Resource,
    UnsupportedConversionError,
)
from bookshelf._core.client import BookshelfClient
from bookshelf._core.config import UNSET, AuthInput
from bookshelf._core.errors import BookshelfError, NotFoundError
from bookshelf._core.retry import RetryPolicy
from bookshelf._generated import models
from bookshelf._produce import (
    Activity,
    AsyncActivity,
    AsyncDraftBook,
    DraftBook,
    PartialRegistrationError,
    RegisterItem,
    RegistrationFailure,
    RegistrationSuccess,
    Used,
)
from bookshelf._produce.facade import AsyncLiveSink, AsyncProduceFacade, LiveSink, ProduceFacade
from bookshelf.cache import ContentCache

_PAGE_SIZE = 100
_MAX_PAGES = 1000


def _missing_book(volume: str, version: str, edition: int | None) -> NotFoundError:
    coordinate = version if edition is None else f"{version}_e{edition:03}"
    return NotFoundError(
        f"no published book {coordinate!r} in volume {volume!r}",
        status_code=404,
    )


class Bookshelf(ProduceFacade):
    """Synchronous facade for consuming, cataloguing, and curating resources."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        auth: AuthInput = UNSET,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        transport: httpx.BaseTransport | None = None,
        cache: ContentCache | None = None,
    ) -> None:
        self._client = BookshelfClient(
            base_url,
            auth=auth,
            timeout=timeout,
            retry=retry,
            transport=transport,
        )
        self._cache = cache if cache is not None else ContentCache()
        self._produce_sink = LiveSink(self._client, self._cache)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the sync transport if it was opened."""
        self._client.close()

    def resource(self, tracking_id: str | UUID) -> Resource:
        """Resolve an exact tracking id into a lean Resource."""
        metadata = self._client.get_resource(tracking_id)
        return Resource(self._client, self._cache, tracking_id, metadata=metadata)

    def book(self, volume: str, version: str, *, edition: int | None = None) -> Book:
        """Resolve a published Book, defaulting to the latest edition."""
        chosen: models.BookListItem | None = None
        if edition is None:
            response = self._client.list_books(
                volume=volume,
                version=version,
                status="published",
                latest_only=True,
                limit=_PAGE_SIZE,
            )
            if response.items:
                chosen = max(response.items, key=lambda item: item.edition)
        else:
            for page in range(_MAX_PAGES):
                response = self._client.list_books(
                    volume=volume,
                    version=version,
                    status="published",
                    limit=_PAGE_SIZE,
                    offset=page * _PAGE_SIZE,
                )
                chosen = next((item for item in response.items if item.edition == edition), None)
                if chosen is not None or not response.has_more:
                    break
            else:
                raise BookshelfError("book lookup exceeded the pagination safety cap")
        if chosen is None:
            raise _missing_book(volume, version, edition)
        entries = self._all_entries(chosen.id)
        return Book(self._client, self._cache, chosen, entries)

    def _all_entries(self, book_id: str) -> list[models.BookEntryItem]:
        entries: list[models.BookEntryItem] = []
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            response = self._client.list_book_entries(book_id, limit=_PAGE_SIZE, cursor=cursor)
            entries.extend(response.items)
            cursor = response.next_cursor
            if cursor is None:
                return entries
        raise BookshelfError("book entry lookup exceeded the pagination safety cap")


class AsyncBookshelf(AsyncProduceFacade):
    """Asynchronous facade for consuming, cataloguing, and curating resources."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        auth: AuthInput = UNSET,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        async_transport: httpx.AsyncBaseTransport | None = None,
        cache: ContentCache | None = None,
    ) -> None:
        self._client = BookshelfClient(
            base_url,
            auth=auth,
            timeout=timeout,
            retry=retry,
            async_transport=async_transport,
        )
        self._cache = cache if cache is not None else ContentCache()
        self._produce_sink = AsyncLiveSink(self._client, self._cache)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close both transport surfaces if either was opened."""
        await self._client.aclose()

    async def resource(self, tracking_id: str | UUID) -> AsyncResource:
        """Resolve an exact tracking id into a lean async Resource."""
        metadata = await self._client.get_resource_async(tracking_id)
        return AsyncResource(self._client, self._cache, tracking_id, metadata=metadata)

    async def book(
        self,
        volume: str,
        version: str,
        *,
        edition: int | None = None,
    ) -> AsyncBook:
        """Resolve a published async Book, defaulting to the latest edition."""
        chosen: models.BookListItem | None = None
        if edition is None:
            response = await self._client.list_books_async(
                volume=volume,
                version=version,
                status="published",
                latest_only=True,
                limit=_PAGE_SIZE,
            )
            if response.items:
                chosen = max(response.items, key=lambda item: item.edition)
        else:
            for page in range(_MAX_PAGES):
                response = await self._client.list_books_async(
                    volume=volume,
                    version=version,
                    status="published",
                    limit=_PAGE_SIZE,
                    offset=page * _PAGE_SIZE,
                )
                chosen = next((item for item in response.items if item.edition == edition), None)
                if chosen is not None or not response.has_more:
                    break
            else:
                raise BookshelfError("book lookup exceeded the pagination safety cap")
        if chosen is None:
            raise _missing_book(volume, version, edition)
        entries = await self._all_entries(chosen.id)
        return AsyncBook(self._client, self._cache, chosen, entries)

    async def _all_entries(self, book_id: str) -> list[models.BookEntryItem]:
        entries: list[models.BookEntryItem] = []
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            response = await self._client.list_book_entries_async(
                book_id,
                limit=_PAGE_SIZE,
                cursor=cursor,
            )
            entries.extend(response.items)
            cursor = response.next_cursor
            if cursor is None:
                return entries
        raise BookshelfError("book entry lookup exceeded the pagination safety cap")


__all__ = [
    "Activity",
    "AsyncActivity",
    "AsyncBook",
    "AsyncBookEntry",
    "AsyncBookshelf",
    "AsyncDraftBook",
    "AsyncResource",
    "Book",
    "BookEntry",
    "Bookshelf",
    "DraftBook",
    "HashMismatchError",
    "PartialRegistrationError",
    "RegisterItem",
    "RegistrationFailure",
    "RegistrationSuccess",
    "Resource",
    "UnsupportedConversionError",
    "Used",
]
