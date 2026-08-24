"""Published Book handles shared by synchronous and asynchronous consumers."""

from collections.abc import Iterator
from uuid import UUID

from bookshelf._consume.presentation import summary_table
from bookshelf._consume.resources import AsyncBookEntry, BookEntry
from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf.cache import ContentCache


class _BookBase:
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

    def _repr_html_(self) -> str:
        entries = ", ".join(sorted(self._entries)) or "none"
        return summary_table(
            "Bookshelf Book",
            {
                "volume": self.metadata.volume_name,
                "version": self.metadata.version,
                "edition": self.metadata.edition,
                "entries": entries,
            },
        )

    def _entry(self, name_in_book: str) -> models.BookEntryItem:
        try:
            return self._entries[name_in_book]
        except KeyError:
            available = ", ".join(sorted(self._entries)) or "(none)"
            raise KeyError(
                f"book {self.metadata.version}_e{self.metadata.edition:03} has no entry "
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

    def __getitem__(self, name_in_book: str) -> AsyncBookEntry:
        return AsyncBookEntry(
            self._client,
            self._cache,
            self.book_id,
            self._entry(name_in_book),
        )


__all__ = ["AsyncBook", "Book"]
