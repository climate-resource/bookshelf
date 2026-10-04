"""The SDK-owned types the public API returns in place of the generated models."""

from pathlib import Path
from typing import cast

import pytest

from bookshelf import Book, BookEntry, ResourceType, Visibility
from bookshelf._consume.volumes import Volume
from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf._records import Facets, identity, known_member, search_results
from bookshelf.cache import ContentCache

BOOK_ID = "0197a000-0000-7000-8000-0000000000b1"
TRACKING_ID = "0197a000-0000-7000-8000-0000000000c1"
TIMESTAMP = "2026-01-01T00:00:00Z"


def test_a_known_value_is_the_member_itself() -> None:
    assert ResourceType("timeseries") is ResourceType.TIMESERIES
    assert Visibility("public") is Visibility.PUBLIC


@pytest.mark.parametrize("enum", [ResourceType, Visibility])
def test_an_unknown_server_value_is_kept_rather_than_refused(
    enum: type[ResourceType] | type[Visibility],
) -> None:
    newer = enum("something-newer")

    assert isinstance(newer, enum)
    assert newer.value == "something-newer"
    assert newer == "something-newer"
    assert newer not in list(enum)


def test_a_caller_supplied_value_must_be_known() -> None:
    assert known_member(models.ResourceType, "figure") is models.ResourceType.figure
    with pytest.raises(ValueError, match="one of: timeseries"):
        known_member(models.ResourceType, "video")


def test_an_entry_of_an_unknown_type_still_resolves_as_bytes(tmp_path: Path) -> None:
    item = models.BookEntryItem.model_validate(
        {
            "entry_id": BOOK_ID,
            "name_in_book": "clip",
            "tracking_id": TRACKING_ID,
            "type": "video",
            "visibility": "partners",
        }
    )
    entry = BookEntry(cast(BookshelfClient, object()), ContentCache(tmp_path), BOOK_ID, item)

    assert entry.resource_type() == "video"
    assert isinstance(entry.resource_type(), ResourceType)
    assert entry.visibility == "partners"
    assert "Read:\n    fetch()  download()  as_path()" in repr(entry)


def test_a_book_states_its_coordinates(tmp_path: Path) -> None:
    record = models.BookListItem.model_validate(
        {
            "id": BOOK_ID,
            "volume_name": "primap-hist",
            "version": "v2.6",
            "edition": 2,
            "status": "published",
            "visibility": "public",
            "metadata": {"maturity": "approved"},
            "created_at": TIMESTAMP,
            "published_at": TIMESTAMP,
        }
    )
    book = Book(cast(BookshelfClient, object()), ContentCache(tmp_path), record, [])

    assert (book.volume, book.version, book.edition) == ("primap-hist", "v2.6", 2)
    assert book.status == "published"
    assert book.visibility is Visibility.PUBLIC
    assert book.metadata == {"maturity": "approved"}
    assert book.published_at is not None


def test_a_volume_states_its_discovery_profile(tmp_path: Path) -> None:
    detail = models.VolumeDetailResponse.model_validate(
        {
            "id": BOOK_ID,
            "name": "primap-hist",
            "owner_org_id": "org",
            "metadata": {"source": "PIK"},
            "discovery": {"title": "PRIMAP-hist", "license": "CC-BY-4.0", "keywords": ["ghg"]},
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
            "versions": [],
            "stats": {
                "total_versions": 0,
                "total_editions": 0,
                "total_resources": 0,
                "total_size_bytes": 0,
            },
        }
    )
    volume = Volume(cast(BookshelfClient, object()), ContentCache(tmp_path), detail, book_ttl=0)

    assert volume.title == "PRIMAP-hist"
    assert volume.license == "CC-BY-4.0"
    assert volume.description is None
    assert volume.discovery["keywords"] == ["ghg"]
    assert volume.metadata == {"source": "PIK"}


def test_search_results_page_through_sdk_summaries() -> None:
    response = models.VolumeListResponse.model_validate(
        {
            "items": [
                {
                    "id": BOOK_ID,
                    "name": "primap-hist",
                    "owner_org_id": "org",
                    "created_at": TIMESTAMP,
                    "updated_at": TIMESTAMP,
                    "discovery": {"license": "CC-BY-4.0", "deprecated": True},
                    "latest_version": "v2.6",
                    "resource_types": ["timeseries", "video"],
                }
            ],
            "total": 3,
            "limit": 1,
            "offset": 0,
            "has_more": True,
        }
    )

    results = search_results(response)
    (summary,) = results

    assert (results.total, results.has_more) == (3, True)
    assert summary.license == "CC-BY-4.0"
    assert summary.deprecated is True
    assert summary.resource_types == (ResourceType.TIMESERIES, ResourceType("video"))


def test_facets_look_up_by_column() -> None:
    facets = Facets(facets=(), categorical_columns=(), numeric_columns=(), total_rows=0)

    with pytest.raises(KeyError):
        facets["scenario"]


def test_an_identity_copies_out_of_the_response() -> None:
    user = models.UserResponse(id="u1", email="a@example.org", permissions=["read"])

    assert identity(user).permissions == ("read",)
