"""Notebook reprs must report the resource type the handle has actually learned.

A book entry may arrive from the API without a type.
Only the handle learns it, by fetching the resource metadata,
so a repr reading the entry instead of the handle reports "unknown" forever.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from bookshelf._consume.resources import AsyncBookEntry, BookEntry
from bookshelf._generated import models
from bookshelf.cache import ContentCache

TRACKING_ID = UUID("11111111-2222-3333-4444-555555555555")
BOOK_ID = UUID("0193f0f3-0000-7000-8000-000000000001")


def _entry(resource_type: models.ResourceType | None) -> models.BookEntryItem:
    """A book entry whose type the API may or may not have filled in."""
    return models.BookEntryItem(
        entry_id=UUID("0193f0f3-0000-7000-8000-0000000000ff"),
        name_in_book="by_country",
        tracking_id=TRACKING_ID,
        type=resource_type,
        visibility=models.Visibility.public,
    )


class _Metadata:
    """The attributes a repr and the fetch path read off a resource record."""

    def __init__(self) -> None:
        self.type = models.ResourceType.timeseries
        self.hash = "sha256:" + "0" * 64
        self.visibility = models.Visibility.public


class _FakeClient:
    """Answers the one metadata call a typeless handle has to make."""

    def __init__(self) -> None:
        self.calls = 0

    def get_resource(self, tracking_id: Any) -> _Metadata:
        self.calls += 1
        return _Metadata()

    async def get_resource_async(self, tracking_id: Any) -> _Metadata:
        self.calls += 1
        return _Metadata()


@pytest.fixture
def cache(tmp_path: Path) -> ContentCache:
    return ContentCache(base_dir=tmp_path)


async def test_an_async_entry_repr_reports_the_type_it_has_fetched(cache: ContentCache) -> None:
    """The regression: the handle knew the type and the repr still said "unknown"."""
    client = _FakeClient()
    entry = AsyncBookEntry(client, cache, BOOK_ID, _entry(None))  # type: ignore[arg-type]

    assert "unknown" in entry._repr_html_(), "a typeless entry has nothing better to say yet"

    await entry._get_type()

    assert "timeseries" in entry._repr_html_()
    assert "unknown" not in entry._repr_html_()


async def test_an_async_entry_repr_uses_the_type_the_api_supplied(cache: ContentCache) -> None:
    """A typed entry never needs the metadata call."""
    client = _FakeClient()
    entry = AsyncBookEntry(
        client,  # type: ignore[arg-type]
        cache,
        BOOK_ID,
        _entry(models.ResourceType.tabular),
    )

    assert "tabular" in entry._repr_html_()
    assert client.calls == 0


def test_a_sync_entry_repr_reports_the_type_it_fetches(cache: ContentCache) -> None:
    """The sync twin resolves the type through its property, so it never says "unknown"."""
    client = _FakeClient()
    entry = BookEntry(client, cache, BOOK_ID, _entry(None))  # type: ignore[arg-type]

    assert "timeseries" in entry._repr_html_()
    assert "unknown" not in entry._repr_html_()


async def test_both_flavours_render_the_same_rows_once_the_type_is_known(
    cache: ContentCache,
) -> None:
    """The two reprs carry the same facts, and differ only in their title."""
    sync_entry = BookEntry(_FakeClient(), cache, BOOK_ID, _entry(None))  # type: ignore[arg-type]
    async_entry = AsyncBookEntry(_FakeClient(), cache, BOOK_ID, _entry(None))  # type: ignore[arg-type]
    await async_entry._get_type()

    sync_html = sync_entry._repr_html_().replace("Bookshelf Book Entry", "TITLE")
    async_html = async_entry._repr_html_().replace("Bookshelf Async Book Entry", "TITLE")

    assert sync_html == async_html
