"""Tests for reading a ``bookshelf://`` reference."""

import pytest

from bookshelf.publisher.reference import BookshelfReference, is_reference


def test_a_full_reference_carries_every_coordinate() -> None:
    reference = BookshelfReference.parse("bookshelf://primap-hist/v2.7_e002/by_country")

    assert reference == BookshelfReference(
        volume="primap-hist", version="v2.7", edition=2, name_in_book="by_country"
    )


def test_a_reference_without_an_entry_names_the_book() -> None:
    reference = BookshelfReference.parse("bookshelf://primap-hist/v2.7_e002")

    assert reference.name_in_book is None
    assert reference.coordinate == "v2.7_e002"


def test_a_reference_without_an_edition_leaves_the_choice_to_the_platform() -> None:
    reference = BookshelfReference.parse("bookshelf://primap-hist/v2.7/by_country")

    assert reference.edition is None
    assert reference.coordinate == "v2.7"


def test_a_version_holding_an_underscore_keeps_it() -> None:
    """Only a trailing ``_e<digits>`` is an edition, so the rest of the version survives."""
    reference = BookshelfReference.parse("bookshelf://ngfs/v4_scenario_e011")

    assert reference.version == "v4_scenario"
    assert reference.edition == 11


@pytest.mark.parametrize(
    "uri",
    [
        "bookshelf://primap-hist",
        "bookshelf://primap-hist/v2.7_e002/by_country/extra",
        "bookshelf:///v2.7_e002",
        "bookshelf://primap-hist//by_country",
    ],
)
def test_a_reference_that_is_not_a_coordinate_is_rejected(uri: str) -> None:
    with pytest.raises(ValueError, match="is not a bookshelf reference"):
        BookshelfReference.parse(uri)


def test_a_uri_of_another_scheme_is_rejected() -> None:
    with pytest.raises(ValueError, match="starts with"):
        BookshelfReference.parse("https://example.invalid/raw.csv")


@pytest.mark.parametrize(
    "uri",
    [
        "bookshelf://primap-hist/v2.7_e002/by_country",
        "bookshelf://primap-hist/v2.7_e002",
        "bookshelf://primap-hist/v2.7",
    ],
)
def test_a_reference_round_trips_through_its_uri(uri: str) -> None:
    assert BookshelfReference.parse(uri).uri == uri


def test_only_the_bookshelf_scheme_is_a_reference() -> None:
    assert is_reference("bookshelf://primap-hist/v2.7_e002")
    assert not is_reference("https://example.invalid/raw.csv")
