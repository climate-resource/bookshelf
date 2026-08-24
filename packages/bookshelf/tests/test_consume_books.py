"""Published Book collection behaviour shared by sync and async consumers."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from bookshelf._consume.books import AsyncBook, Book
from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf.cache import ContentCache


def _metadata() -> models.BookListItem:
    return models.BookListItem(
        id="0197a000-0000-7000-8000-0000000000b1",
        volume_name="example",
        version="v1.0.0",
        edition=1,
        status=models.BookStatus.published,
        visibility=models.Visibility.public,
        metadata={},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _entry(name: str, uuid_seed: int) -> models.BookEntryItem:
    return models.BookEntryItem(
        entry_id=UUID(int=uuid_seed),
        name_in_book=name,
        tracking_id=UUID(int=uuid_seed + 10),
        visibility=models.Visibility.public,
    )


def test_books_iterate_over_entry_names_in_platform_order(tmp_path: Path) -> None:
    client = cast(BookshelfClient, object())
    cache = ContentCache(base_dir=tmp_path)
    entries = [_entry("by_country", 1), _entry("by_region", 2)]

    assert list(Book(client, cache, _metadata(), entries)) == ["by_country", "by_region"]
    assert list(AsyncBook(client, cache, _metadata(), entries)) == ["by_country", "by_region"]
