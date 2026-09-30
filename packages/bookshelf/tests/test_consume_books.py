"""Published Book collection behaviour shared by sync and async consumers."""

from pathlib import Path
from typing import cast

import pytest

from bookshelf import EntryNotFoundError, NotFoundError
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


@pytest.mark.parametrize("book_type", [Book, AsyncBook])
def test_a_missing_entry_is_not_found_and_a_key_error(
    tmp_path: Path, book_type: type[Book] | type[AsyncBook]
) -> None:
    client = cast(BookshelfClient, object())
    metadata = models.BookListItem.model_construct(
        id="0197a000-0000-7000-8000-0000000000b1", version="v1.0", edition=1
    )
    entries = [models.BookEntryItem.model_construct(name_in_book="by_country")]
    book = book_type(client, ContentCache(base_dir=tmp_path), metadata, entries)

    with pytest.raises(EntryNotFoundError) as caught:
        book["by_region"]

    assert isinstance(caught.value, NotFoundError)
    assert isinstance(caught.value, KeyError)
    assert str(caught.value) == "book v1.0_e001 has no entry 'by_region', available: by_country"
