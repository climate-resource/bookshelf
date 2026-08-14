"""Tests for the bundle contract, through the :class:`Bundle` interface."""

import importlib.metadata
from pathlib import Path

import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._core.hashing import canonical_json_bytes
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

    bundle.validate()

    assert bundle.require_framing().volume == "example"
    assert len(bundle.require_framing().entries) == 2


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
    bundle.manifest.book.entries[0].name = "absent"  # type: ignore[union-attr]

    with pytest.raises(InvalidBundleError, match="book entry 'absent' has no resource"):
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

    assert f"resource {resource.name!r} has hash {resource.hash}, got sha256:" in str(raised.value)


def test_a_managed_resource_with_no_bytes_is_invalid(make_bundle: BundleFactory) -> None:
    """A manifest record whose byte file is gone is a refusal, not a crash."""
    bundle = make_bundle()
    resource = bundle.manifest.resources[0]
    (bundle.resources_dir / resource_filename(resource.hash, resource.type)).unlink()

    with pytest.raises(InvalidBundleError, match="has no bytes in the bundle"):
        bundle.validate()


def test_a_crafted_hash_is_invalid_rather_than_unreadable(make_bundle: BundleFactory) -> None:
    """A hash that names no byte file is a refusal, not an attempt to read a traversed path."""
    bundle = make_bundle()
    bundle.manifest.resources[0].hash = "sha256:../../etc/passwd"

    with pytest.raises(InvalidBundleError, match="non-canonical hash"):
        bundle.validate()


def test_a_pointer_is_not_re_hashed(tmp_path: Path) -> None:
    """A pointer has no byte file, so hashing one would fail on a valid bundle."""
    bundle = Bundle(tmp_path / "bundle")
    bundle.set_book(BundleBook(volume="example", version="v1.0.0"))
    bundle.add_pointer(
        external_uri="https://example.invalid/data.csv",
        hash_=synthesise_pointer_hash(
            type_="tabular", external_uri="https://example.invalid/data.csv"
        ),
        type_="tabular",
        name="entry-0",
    )
    bundle.add_book_entry(name="entry-0")
    bundle.mark_book_published()

    bundle.validate()


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


def test_a_resource_name_round_trips(make_bundle: BundleFactory) -> None:
    written = make_bundle()

    reloaded = Bundle.read(written.root)

    assert reloaded.manifest.resources[0].name == "entry-0"


def test_an_invalid_bundle_is_a_bookshelf_error(make_bundle: BundleFactory) -> None:
    """One catch reaches every bundle refusal, so a caller never enumerates the rules."""
    bundle = make_bundle(published=False)

    with pytest.raises(BookshelfError):
        bundle.validate()


def test_a_written_bundle_records_the_pyarrow_that_wrote_its_bytes(
    make_bundle: BundleFactory,
) -> None:
    """Parquet is not stable across pyarrow versions, so the writer explains a hash change."""
    written = make_bundle()

    reloaded = Bundle.read(written.root)

    assert reloaded.manifest.writer is not None
    assert reloaded.manifest.writer.pyarrow == importlib.metadata.version("pyarrow")


def _read_manifest_text(tmp_path: Path, text: str) -> Bundle:
    """Write a hand-rolled manifest and read it back as a bundle."""
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "manifest.lock").write_text(text)
    return Bundle.read(root)


def test_a_manifest_with_no_writer_block_loads_with_writer_none(tmp_path: Path) -> None:
    """A bundle written before the header existed must still load."""
    loaded = _read_manifest_text(tmp_path, "schema_version: '3.0'\nresources: []\n")

    assert loaded.manifest.writer is None


def test_an_unknown_key_inside_writer_is_ignored(tmp_path: Path) -> None:
    """The header is additive, so a later client may record more than pyarrow."""
    loaded = _read_manifest_text(
        tmp_path,
        "schema_version: '3.1'\nresources: []\nwriter:\n  pyarrow: 1.2.3\n  polars: 9.9.9\n",
    )

    assert loaded.manifest.writer is not None
    assert loaded.manifest.writer.pyarrow == "1.2.3"


def test_a_manifest_declaring_an_older_major_is_refused(tmp_path: Path) -> None:
    """A v2 bundle keys its resources by tracking id, which this reader cannot name."""
    with pytest.raises(InvalidBundleError, match="keys its resources by tracking id"):
        _read_manifest_text(tmp_path, "schema_version: '2.0'\nresources: []\n")


def test_a_manifest_declaring_a_newer_major_is_refused(tmp_path: Path) -> None:
    """Reading it here would drop whatever the new major added meaning to."""
    with pytest.raises(InvalidBundleError, match="newer major"):
        _read_manifest_text(tmp_path, "schema_version: '4.0'\nresources: []\n")


def test_a_newer_minor_still_loads(tmp_path: Path) -> None:
    """A minor is additive, so the models drop what they do not know and keep the rest."""
    loaded = _read_manifest_text(tmp_path, "schema_version: '3.9'\nresources: []\n")

    assert loaded.manifest.schema_version == "3.9"


def test_the_synthesised_pointer_hash_matches_the_backend_seed() -> None:
    """Pin the seed the backend hashes, because the two have to agree byte for byte.

    The backend computes this in ``_synthesise_hash``
    (``backend/src/bookshelf_api/services/registration.py``)
    over ``{type, sorted(locations)}``.
    Adding a field on either side changes the digest,
    and a pointer registered by the SDK then stops colliding with its canonical resource.
    """
    uri = "https://example.invalid/data.csv"
    seed = b'{"locations":[["external","https://example.invalid/data.csv"]],"type":"tabular"}'

    assert canonical_json_bytes({"type": "tabular", "locations": [["external", uri]]}) == seed
    assert synthesise_pointer_hash(type_="tabular", external_uri=uri) == (
        "sha256:7cf03fca2d1e24ee4c78e8d6f814e47b60ca5203a001e034bd2c8240e4a90bbe"
    )
