"""Published Book handles shared by synchronous and asynchronous consumers."""

from collections.abc import Iterator
from uuid import UUID

from bookshelf._consume.presentation import Sections, summary_table, summary_text
from bookshelf._consume.resources import AsyncBookEntry, BookEntry, describe_type
from bookshelf._core.client import BookshelfClient
from bookshelf._core.names import book_coordinate
from bookshelf._generated import models
from bookshelf.cache import ContentCache


class _BookBase:
    _title = "Bookshelf Book"

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        metadata: models.BookListItem,
        entries: list[models.BookEntryItem],
    ) -> None:
        self._client = client
        self._cache = cache
        self.metadata = metadata
        self.book_id = UUID(metadata.id)
        self._entries = {entry.name_in_book: entry for entry in entries}

    @property
    def entry_names(self) -> tuple[str, ...]:
        """The entries this book indexes, in the order the platform lists them."""
        return tuple(self._entries)

    def __iter__(self) -> Iterator[str]:
        """Iterate over entry names in the order the platform lists them."""
        return iter(self._entries)

    def _summary(self) -> tuple[str, Sections]:
        metadata = self.metadata
        coordinate = book_coordinate(metadata.version, metadata.edition)
        return (
            f"{self._title} {metadata.volume_name!r} {coordinate} (entries: {len(self._entries)})",
            {
                "Book": {
                    "status": metadata.status.value,
                    "visibility": metadata.visibility.value,
                    "book_id": self.book_id,
                },
                "Entries": {
                    name: describe_type(entry.type) for name, entry in self._entries.items()
                },
                "Access": [f'book["{next(iter(self._entries), "<name>")}"]'],
            },
        )

    def __repr__(self) -> str:
        return summary_text(*self._summary())

    def _repr_html_(self) -> str:
        return summary_table(*self._summary())

    def _entry(self, name_in_book: str) -> models.BookEntryItem:
        try:
            return self._entries[name_in_book]
        except KeyError:
            available = ", ".join(sorted(self._entries)) or "(none)"
            raise KeyError(
                f"book {book_coordinate(self.metadata.version, self.metadata.edition)} "
                f"has no entry "
                f"{name_in_book!r}, available: {available}"
            ) from None


class Book(_BookBase):
    """A resolved published Book indexed by Entry name."""

    def __getitem__(self, name_in_book: str) -> BookEntry:
        return BookEntry(
            self._client,
            self._cache,
            self.book_id,
            self._entry(name_in_book),
        )


class AsyncBook(_BookBase):
    """An asynchronously resolved published Book indexed by Entry name."""

    _title = "Bookshelf Async Book"

    def __getitem__(self, name_in_book: str) -> AsyncBookEntry:
        return AsyncBookEntry(
            self._client,
            self._cache,
            self.book_id,
            self._entry(name_in_book),
        )


__all__ = ["AsyncBook", "Book"]
