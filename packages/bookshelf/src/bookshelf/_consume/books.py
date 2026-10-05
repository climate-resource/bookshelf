"""Published Book handles."""

from collections.abc import Iterator
from datetime import datetime
from typing import Any
from uuid import UUID

from bookshelf._consume.presentation import Describable, Sections
from bookshelf._consume.resources import BookEntry, describe_type
from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import EntryNotFoundError
from bookshelf._core.names import book_coordinate
from bookshelf._generated import models
from bookshelf._records import Visibility, visibility
from bookshelf.cache import ContentCache


class Book(Describable):
    """A resolved published Book indexed by Entry name."""

    _title = "Bookshelf Book"
    book_id: UUID

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        metadata: models.BookListItem,
        entries: list[models.BookEntryItem],
    ) -> None:
        self._client = client
        self._cache = cache
        self._record = metadata
        self.book_id = UUID(metadata.id)
        """The platform's id for this book."""
        self._entries = {entry.name_in_book: entry for entry in entries}

    @property
    def volume(self) -> str:
        """The name of the volume this book belongs to."""
        return self._record.volume_name

    @property
    def version(self) -> str:
        """The upstream data version this book releases."""
        return self._record.version

    @property
    def edition(self) -> int:
        """The edition number, which increases each time the version is reprocessed."""
        return self._record.edition

    @property
    def status(self) -> str:
        """The publication status, ``published`` for every book a consumer can resolve."""
        return self._record.status.value

    @property
    def visibility(self) -> Visibility:
        """Who can read this book."""
        return visibility(self._record.visibility)

    @property
    def published_at(self) -> datetime | None:
        """When the edition was published."""
        return self._record.published_at

    @property
    def metadata(self) -> dict[str, Any]:
        """The free-form metadata the book was published with."""
        return dict(self._record.metadata)

    @property
    def entry_names(self) -> tuple[str, ...]:
        """The entries this book indexes, in the order the platform lists them."""
        return tuple(self._entries)

    def __iter__(self) -> Iterator[str]:
        """Iterate over entry names in the order the platform lists them."""
        return iter(self._entries)

    def _summary(self) -> tuple[str, Sections]:
        coordinate = book_coordinate(self.version, self.edition)
        return (
            f"{self._title} {self.volume!r} {coordinate} (entries: {len(self._entries)})",
            {
                "Book": {
                    "status": self.status,
                    "visibility": self.visibility.value,
                    "book_id": self.book_id,
                },
                "Entries": {
                    name: describe_type(entry.type) for name, entry in self._entries.items()
                },
                "Access": [f'book["{next(iter(self._entries), "<name>")}"]'],
            },
        )

    def _entry(self, name_in_book: str) -> models.BookEntryItem:
        try:
            return self._entries[name_in_book]
        except KeyError:
            available = ", ".join(sorted(self._entries)) or "(none)"
            raise EntryNotFoundError(
                f"book {book_coordinate(self.version, self.edition)} "
                f"has no entry {name_in_book!r}, available: {available}",
                status_code=404,
            ) from None

    def __getitem__(self, name_in_book: str) -> BookEntry:
        """Look up one entry by name, raising EntryNotFoundError for a name the book does not index."""
        return BookEntry(
            self._client,
            self._cache,
            self.book_id,
            self._entry(name_in_book),
        )


__all__ = ["Book"]
