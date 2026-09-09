"""Tests for reading a ``bookshelf://`` reference."""

import pytest

from bookshelf.publisher.reference import (
    BookshelfReference,
    DigestReference,
    is_reference,
    parse_reference,
)


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


_HEX = "ab" * 32


def test_a_digest_reference_carries_the_canonical_hash() -> None:
    reference = parse_reference(f"bookshelf://sha256/{_HEX.upper()}")

    assert reference == DigestReference(hash=f"sha256:{_HEX}")
    assert reference.uri == f"bookshelf://sha256/{_HEX}"


def test_a_coordinate_still_parses_through_the_shared_entry_point() -> None:
    assert parse_reference("bookshelf://primap-hist/v2.7_e002/by_country") == BookshelfReference(
        volume="primap-hist", version="v2.7", edition=2, name_in_book="by_country"
    )


def test_a_volume_named_sha256_is_reachable_by_any_other_version() -> None:
    """Only sixty-four hex characters after sha256/ make a digest, so the volume name is not lost."""
    reference = parse_reference("bookshelf://sha256/v1.0_e001")

    assert reference == BookshelfReference(volume="sha256", version="v1.0", edition=1)


@pytest.mark.parametrize(
    "uri",
    [
        "bookshelf://sha256/" + "a" * 63,
        "bookshelf://sha256/" + "g" * 64,
        f"bookshelf://sha256/{_HEX}/entry",
    ],
)
def test_a_malformed_digest_is_refused(uri: str) -> None:
    with pytest.raises(ValueError, match="digest reference"):
        DigestReference.parse(uri)


def test_the_coordinate_parser_refuses_a_digest() -> None:
    with pytest.raises(ValueError, match="by digest rather than by coordinate"):
        BookshelfReference.parse(f"bookshelf://sha256/{_HEX}")


@pytest.mark.parametrize(
    "uri",
    ["bookshelf://sha256/" + "a" * 63, f"bookshelf://sha256/{_HEX}/entry"],
)
def test_a_malformed_digest_is_refused_rather_than_read_as_a_book(uri: str) -> None:
    with pytest.raises(ValueError, match="64 hex characters"):
        parse_reference(uri)
