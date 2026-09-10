"""Notebook reprs must report the resource type the handle has actually learned.

A book entry may arrive from the API without a type.
Only the handle learns it, by fetching the resource metadata,
so a repr reading the entry instead of the handle reports "unknown" forever.
"""

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from bookshelf._consume import resources
from bookshelf._consume.books import Book
from bookshelf._consume.resources import AsyncBookEntry, BookEntry, Resource
from bookshelf._core.errors import APIError
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
        self.tracking_id = TRACKING_ID
        self.type = models.ResourceType.timeseries
        self.hash = "sha256:" + "0" * 64
        self.visibility = models.Visibility.public


class _FakeClient:
    """Answers the one metadata call a typeless handle has to make."""

    def __init__(self) -> None:
        self.base_url = "https://bookshelf.test"
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


def _book(*entries: models.BookEntryItem) -> Book:
    metadata = models.BookListItem(
        id=str(BOOK_ID),
        volume_name="primap-hist",
        version="v2.6",
        edition=5,
        status=models.BookStatus.published,
        visibility=models.Visibility.public,
        metadata={},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return Book(_FakeClient(), ContentCache(), metadata, list(entries))  # type: ignore[arg-type]


def test_printing_a_book_names_its_entries_and_their_types(cache: ContentCache) -> None:
    """The point of the repr: what is in here, and what do I index it by."""
    book = _book(_entry(models.ResourceType.timeseries))

    printed = repr(book)

    assert "Bookshelf Book 'primap-hist' v2.6_e005 (entries: 1)" in printed
    assert "Entries:\n    by_country  timeseries" in printed
    assert 'book["by_country"]' in printed


def test_a_book_repr_survives_having_no_entries() -> None:
    """An empty book still has to print, and the index hint has no name to offer."""
    assert 'book["<name>"]' in repr(_book())


def test_printing_an_entry_names_the_readers_its_type_supports(cache: ContentCache) -> None:
    """A timeseries entry offers every converter, and a document offers only the byte readers.

    A document answers no exploration call either,
    and an empty section is left out rather than rendered as "(none)".
    """
    timeseries = repr(
        BookEntry(_FakeClient(), cache, BOOK_ID, _entry(models.ResourceType.timeseries))
    )  # type: ignore[arg-type]
    document = repr(BookEntry(_FakeClient(), cache, BOOK_ID, _entry(models.ResourceType.document)))  # type: ignore[arg-type]

    assert "as_scmrun()" in timeseries
    assert "schema()" in timeseries
    assert "as_scmrun()" not in document
    assert "fetch()" in document
    assert "Explore" not in document


def test_the_two_reprs_report_the_same_facts(cache: ContentCache) -> None:
    """Text and HTML both render one row mapping, so neither can go stale on its own."""
    entry = BookEntry(_FakeClient(), cache, BOOK_ID, _entry(models.ResourceType.tabular))  # type: ignore[arg-type]

    text = repr(entry)
    html = entry._repr_html_()

    for value in ("by_country", "tabular", str(TRACKING_ID), "as_polars()"):
        assert value in text
        assert value in html


class _UnreachableClient:
    """The platform a debugger session cannot reach, or is not authorised against."""

    base_url = "https://bookshelf.invalid"

    def get_resource(self, tracking_id: Any) -> _Metadata:
        raise APIError("not authorized", status_code=401)


def test_a_sync_entry_repr_survives_an_unreachable_platform(cache: ContentCache) -> None:
    """Printing a handle is what you do when things are already going wrong."""
    entry = BookEntry(_UnreachableClient(), cache, BOOK_ID, _entry(None))  # type: ignore[arg-type]

    printed = repr(entry)

    assert "unknown" in printed
    assert "by_country" in printed


def test_a_sync_resource_repr_survives_an_unreachable_platform(cache: ContentCache) -> None:
    """The lean handle knows only its tracking id, and says so rather than raising."""
    resource = Resource(_UnreachableClient(), cache, TRACKING_ID)  # type: ignore[arg-type]

    printed = repr(resource)

    assert "unknown" in printed
    assert str(TRACKING_ID) in printed
    assert "hash" not in printed


class _HangingClient:
    """A platform that accepts the connection and then never answers."""

    base_url = "https://bookshelf.invalid"

    def __init__(self) -> None:
        self.released = threading.Event()

    def get_resource(self, tracking_id: Any) -> _Metadata:
        self.released.wait(timeout=30)
        return _Metadata()


def test_a_repr_gives_up_rather_than_holding_a_debugger(
    cache: ContentCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hung platform must not hold a printed line for the client's full timeout."""
    monkeypatch.setattr(resources, "_REPR_TIMEOUT", 0.05)
    client = _HangingClient()
    resource = Resource(client, cache, TRACKING_ID)  # type: ignore[arg-type]

    started = time.monotonic()
    printed = repr(resource)
    waited = time.monotonic() - started
    client.released.set()

    assert waited < 5, "the repr waited on the platform instead of giving up"
    assert "unknown" in printed
    assert str(TRACKING_ID) in printed
