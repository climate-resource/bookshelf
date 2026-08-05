"""Mutable draft-book handles for producer workflows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Self
from uuid import UUID

from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf._produce.types import HasTrackingId


class DraftBook:
    """Mutable synchronous draft-book handle."""

    def __init__(self, client: BookshelfClient, detail: models.BookDetail) -> None:
        self._client = client
        self.metadata = detail

    @property
    def book_id(self) -> UUID:
        return self.metadata.book_id

    @property
    def status(self) -> str:
        return self.metadata.status

    def attach(
        self,
        resource: HasTrackingId | str | UUID,
        *,
        name_in_book: str,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
    ) -> models.BookEntryAttachResponse:
        """Attach a resource under a book-local name and optional entry dictionary.

        Omitting ``data_dictionary`` preserves the dictionary on an existing entry.
        Pass an empty sequence to clear it.
        """
        tracking_id = (
            UUID(str(resource))
            if isinstance(resource, str | UUID)
            else UUID(str(resource.tracking_id))
        )
        request = (
            models.BookEntryAttach(tracking_id=tracking_id, name_in_book=name_in_book)
            if data_dictionary is None
            else models.BookEntryAttach(
                tracking_id=tracking_id,
                name_in_book=name_in_book,
                data_dictionary=list(data_dictionary),
            )
        )
        return self._client.attach_entry(str(self.book_id), request)

    def publish(self) -> Self:
        """Publish the assembled draft and update this handle in place."""
        self.metadata = self._client.publish_book(str(self.book_id))
        return self


class AsyncDraftBook:
    """Mutable asynchronous draft-book handle."""

    def __init__(self, client: BookshelfClient, detail: models.BookDetail) -> None:
        self._client = client
        self.metadata = detail

    @property
    def book_id(self) -> UUID:
        return self.metadata.book_id

    @property
    def status(self) -> str:
        return self.metadata.status

    async def attach(
        self,
        resource: HasTrackingId | str | UUID,
        *,
        name_in_book: str,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
    ) -> models.BookEntryAttachResponse:
        """Attach a resource under a book-local name and optional entry dictionary.

        Omitting ``data_dictionary`` preserves the dictionary on an existing entry.
        Pass an empty sequence to clear it.
        """
        tracking_id = (
            UUID(str(resource))
            if isinstance(resource, str | UUID)
            else UUID(str(resource.tracking_id))
        )
        request = (
            models.BookEntryAttach(tracking_id=tracking_id, name_in_book=name_in_book)
            if data_dictionary is None
            else models.BookEntryAttach(
                tracking_id=tracking_id,
                name_in_book=name_in_book,
                data_dictionary=list(data_dictionary),
            )
        )
        return await self._client.attach_entry_async(str(self.book_id), request)

    async def publish(self) -> Self:
        """Publish the assembled draft and update this handle in place."""
        self.metadata = await self._client.publish_book_async(str(self.book_id))
        return self


__all__ = ["AsyncDraftBook", "DraftBook"]
