"""Published Book collection behaviour shared by sync and async consumers."""

from pathlib import Path
from typing import cast

from bookshelf._consume.books import AsyncBook, Book
from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf.cache import ContentCache


def test_books_iterate_over_entry_names_in_platform_order(tmp_path: Path) -> None:
    client = cast(BookshelfClient, object())
    cache = ContentCache(base_dir=tmp_path)
    metadata = models.BookListItem.model_construct(id="0197a000-0000-7000-8000-0000000000b1")
    entries = [
        models.BookEntryItem.model_construct(name_in_book=name)
        for name in ("by_country", "by_region")
    ]

    assert list(Book(client, cache, metadata, entries)) == ["by_country", "by_region"]
    assert list(AsyncBook(client, cache, metadata, entries)) == ["by_country", "by_region"]
