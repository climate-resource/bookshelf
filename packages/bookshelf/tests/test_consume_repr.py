"""Notebook reprs must report the resource type the handle has actually learned.

A book entry may arrive from the API without a type.
Only the handle learns it, by fetching the resource metadata,
so a repr reading the entry instead of the handle reports "unknown" forever.
A repr never fetches anything itself.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from bookshelf import UnsupportedConversionError
from bookshelf._consume.books import Book
from bookshelf._consume.resources import BookEntry, Resource
from bookshelf._generated import models
from bookshelf._produce import resources as produce
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


@pytest.fixture
def cache(tmp_path: Path) -> ContentCache:
    return ContentCache(base_dir=tmp_path)


def test_an_entry_repr_uses_the_type_the_api_supplied(cache: ContentCache) -> None:
    """A typed entry never needs the metadata call."""
    client = _FakeClient()
    entry = BookEntry(
        client,  # type: ignore[arg-type]
        cache,
        BOOK_ID,
        _entry(models.ResourceType.tabular),
    )

    assert "tabular" in entry._repr_html_()
    assert client.calls == 0


def test_an_entry_repr_reports_the_type_it_has_fetched(cache: ContentCache) -> None:
    client = _FakeClient()
    entry = BookEntry(client, cache, BOOK_ID, _entry(None))  # type: ignore[arg-type]

    assert "unknown" in entry._repr_html_()
    assert client.calls == 0

    entry.resource_type()

    assert "timeseries" in entry._repr_html_()


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
    assert "series_metadata()" in timeseries
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


class _ForbiddenClient:
    """A platform the repr must never reach."""

    base_url = "https://bookshelf.invalid"

    def get_resource(self, tracking_id: Any) -> _Metadata:
        raise AssertionError("printing a handle contacted the platform")


@pytest.mark.parametrize("handle", [Resource, BookEntry])
def test_printing_a_handle_never_contacts_the_platform(cache: ContentCache, handle: type) -> None:
    """Printing a handle is what you do when things are already going wrong."""
    if handle is BookEntry:
        printed = repr(BookEntry(_ForbiddenClient(), cache, BOOK_ID, _entry(None)))  # type: ignore[arg-type]
    else:
        printed = repr(Resource(_ForbiddenClient(), cache, TRACKING_ID))  # type: ignore[arg-type]

    assert "unknown" in printed
    assert str(TRACKING_ID) in printed
    assert "hash" not in printed


def test_a_registered_resource_names_itself_once(cache: ContentCache) -> None:
    """The producer flavour declares its own title, so nothing rewrites the consumed one."""
    resource = produce.Resource(
        _FakeClient(),  # type: ignore[arg-type]
        cache,
        TRACKING_ID,
        resource_type=models.ResourceType.timeseries,
        name="raw",
    )

    printed = repr(resource)

    assert printed.startswith("<Registered Resource (timeseries)>")
    assert "Registered Registered" not in printed
    assert "Bookshelf" not in printed
    assert "name    raw" in printed


class _NoSchemaClient(_ForbiddenClient):
    def get_book_resource_schema(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a non-timeseries entry asked the platform for its series")


def test_series_metadata_refuses_an_entry_that_is_not_a_timeseries(cache: ContentCache) -> None:
    entry = BookEntry(_NoSchemaClient(), cache, BOOK_ID, _entry(models.ResourceType.tabular))  # type: ignore[arg-type]

    with pytest.raises(UnsupportedConversionError, match="series_metadata"):
        entry.series_metadata()


def test_unsupported_conversion_error_belongs_to_the_root_package() -> None:
    assert UnsupportedConversionError.__module__ == "bookshelf"
