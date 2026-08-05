"""Tests for the bundle contract, through the :class:`Bundle` interface."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf.publisher.bundle import (
    Bundle,
    BundleBook,
    InvalidBundleError,
    resource_filename,
    synthesise_pointer_hash,
)
from tests.conftest import BundleFactory


def test_a_recorded_published_book_validates(make_bundle: BundleFactory) -> None:
    bundle = make_bundle(entries=2)

    framing = bundle.validate()

    assert framing.volume == "example"
    assert len(framing.entries) == 2


def test_a_bundle_with_no_book_framing_is_invalid(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")

    with pytest.raises(InvalidBundleError, match="no book framing"):
        bundle.validate()


def test_a_bundle_that_is_still_a_draft_is_invalid(make_bundle: BundleFactory) -> None:
    bundle = make_bundle(published=False)

    with pytest.raises(InvalidBundleError, match="does not record a publish operation"):
        bundle.validate()


def test_a_book_with_no_entries_is_invalid(make_bundle: BundleFactory) -> None:
    bundle = make_bundle(entries=0)

    with pytest.raises(InvalidBundleError, match="no book entries"):
        bundle.validate()


def test_an_entry_without_its_resource_is_invalid(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    bundle.manifest.book.entries[0].tracking_id = uuid4()  # type: ignore[union-attr]

    with pytest.raises(InvalidBundleError, match="book entry 'entry-0' has no resource"):
        bundle.validate()


def test_managed_bytes_are_re_hashed_against_the_manifest(make_bundle: BundleFactory) -> None:
    """A bundle edited after recording must not publish content no reviewer saw."""
    bundle = make_bundle()
    resource = bundle.manifest.resources[0]
    (bundle.resources_dir / resource_filename(resource.hash, resource.type)).write_bytes(
        b"tampered"
    )

    with pytest.raises(InvalidBundleError) as raised:
        bundle.validate()

    assert f"resource {resource.tracking_id} has hash {resource.hash}, got sha256:" in str(
        raised.value
    )


def test_a_pointer_is_not_re_hashed(tmp_path: Path) -> None:
    """A pointer has no byte file, so hashing one would fail on a valid bundle."""
    bundle = Bundle(tmp_path / "bundle")
    bundle.set_book(BundleBook(volume="example", version="v1.0.0"))
    pointer = bundle.add_pointer(
        external_uri="https://example.invalid/data.csv",
        hash_=synthesise_pointer_hash(
            type_="tabular", external_uri="https://example.invalid/data.csv"
        ),
        type_="tabular",
        tracking_id=uuid4(),
    )
    bundle.add_book_entry(name_in_book="entry-0", tracking_id=pointer.tracking_id)
    bundle.mark_book_published()

    assert bundle.validate().entries[0].name_in_book == "entry-0"


def test_require_framing_returns_the_recorded_book(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()

    assert bundle.require_framing().version == "v1.0.0"


def test_require_framing_refuses_a_resources_only_bundle(tmp_path: Path) -> None:
    with pytest.raises(InvalidBundleError, match="no book framing"):
        Bundle(tmp_path / "bundle").require_framing()


def test_read_validated_returns_a_bundle_that_keeps_its_contract(
    make_bundle: BundleFactory,
) -> None:
    written = make_bundle(entries=2)

    loaded = Bundle.read_validated(written.root)

    assert len(loaded.manifest.resources) == 2


def test_read_validated_refuses_a_bundle_tampered_with_on_disk(
    make_bundle: BundleFactory,
) -> None:
    written = make_bundle()
    resource = written.manifest.resources[0]
    (written.resources_dir / resource_filename(resource.hash, resource.type)).write_bytes(
        b"tampered"
    )

    with pytest.raises(InvalidBundleError, match="has hash"):
        Bundle.read_validated(written.root)


def test_read_leaves_a_draft_loadable(make_bundle: BundleFactory) -> None:
    """Replay keeps the unvalidated read, because a bundle recorded as a draft replays as one."""
    written = make_bundle(published=False)

    loaded = Bundle.read(written.root)

    assert loaded.require_framing().published is False


def test_tracking_ids_round_trip_as_uuids(make_bundle: BundleFactory) -> None:
    written = make_bundle()

    reloaded = Bundle.read(written.root)

    assert isinstance(reloaded.manifest.resources[0].tracking_id, UUID)


def test_an_invalid_bundle_is_a_bookshelf_error(make_bundle: BundleFactory) -> None:
    """One catch reaches every bundle refusal, so a caller never enumerates the rules."""
    bundle = make_bundle(published=False)

    with pytest.raises(BookshelfError):
        bundle.validate()
