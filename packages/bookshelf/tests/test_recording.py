"""Tests for the bundle-backed producer recording adapter."""

from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.types import RegisterItem
from bookshelf.cache import ContentCache
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.record import _record_processing
from bookshelf.publisher.recording import RecordingActivity, RecordingSink


def _sink(bundle: Bundle, cache_path: Path) -> RecordingSink:
    return RecordingSink(bundle, Mock(spec=BookshelfClient), ContentCache(cache_path))


def _activity(bundle: Bundle, cache_path: Path) -> RecordingActivity:
    return RecordingActivity(
        bundle,
        Mock(spec=BookshelfClient),
        ContentCache(cache_path),
        activity_id=uuid4(),
        kind="run",
        code_ref="test",
        config={},
        runner_name="pytest",
        names={},
    )


def test_atomic_register_many_commits_the_complete_batch(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")

    with _activity(bundle, tmp_path / "cache") as activity:
        resources = activity.register_many(
            [
                RegisterItem(b"first", type="document", name="first"),
                RegisterItem(b"second", type="document", name="second"),
            ],
            atomic=True,
        )

    assert [resource.name for resource in resources] == [  # type: ignore[attr-defined]
        resource.name for resource in bundle.manifest.resources
    ]
    assert [bundle.resource_bytes(resource) for resource in bundle.manifest.resources] == [
        b"first",
        b"second",
    ]


def test_atomic_register_many_does_not_record_a_partial_batch(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    activity = _activity(bundle, tmp_path / "cache")

    with activity, pytest.raises(TypeError, match="Cannot serialise"):
        activity.register_many(
            [
                RegisterItem(b"first", type="document", name="first"),
                RegisterItem(object(), type="document", name="second"),
            ],
            atomic=True,
        )

    assert bundle.manifest.activity is None
    assert bundle.manifest.resources == []
    assert not bundle.resources_dir.exists()


def test_a_later_batch_does_not_rewrite_earlier_lineage(tmp_path: Path) -> None:
    """A recorded input belongs to the resource that consumed it.

    Recording the notebook documents happens after the build has registered its
    outputs, so a batch that back-filled its merged inputs across the whole
    manifest would hand the raw input to every resource, including itself.
    """
    bundle = Bundle(tmp_path / "bundle")

    with _activity(bundle, tmp_path / "cache") as activity:
        raw = activity.register(b"raw", type="tabular", name="raw")
        activity.register(b"derived", type="tabular", name="derived", used=[raw.tracking_id])
        activity.register_many([RegisterItem(b"notebook", type="document", name="notebook")])

    recorded = {resource.name: resource.used for resource in bundle.manifest.resources}

    assert recorded["raw"] == [], "the raw input consumed nothing and must not cite itself"
    assert recorded["derived"] == ["raw"]
    assert recorded["notebook"] == ["raw"]


def test_drafting_a_book_reseeds_the_sinks_default_tier(tmp_path: Path) -> None:
    """The book's declared tier is what the resources registered after it record as."""
    sink = _sink(Bundle(tmp_path / "bundle"), tmp_path / "cache")

    assert sink.default_visibility is models.Visibility.hidden

    sink.draft_book("my-dataset", version="v1.0.0", license="MIT", visibility="public")

    assert sink.default_visibility is models.Visibility.public


def test_a_book_that_declares_no_tier_leaves_the_default_alone(tmp_path: Path) -> None:
    sink = _sink(Bundle(tmp_path / "bundle"), tmp_path / "cache")
    sink.default_visibility = models.Visibility.org

    book = sink.draft_book("my-dataset", version="v1.0.0", license="MIT")

    assert book.metadata.visibility is models.Visibility.org
    assert sink.default_visibility is models.Visibility.org


def _record(root: Path, cache_path: Path) -> bytes:
    """Record one fixed build and return the manifest bytes it wrote."""
    bundle = Bundle(root)
    sink = _sink(bundle, cache_path)
    with sink.activity(code_ref="repo@sha", config={"year": 2026}) as activity:
        activity.register(b"payload", type="document", name="data")
    bundle.write()
    return bundle.manifest_path.read_bytes()


def test_recording_the_same_build_twice_produces_identical_manifests(tmp_path: Path) -> None:
    """The activity id names what the build is, so a re-record is byte for byte the same."""
    first = _record(tmp_path / "first", tmp_path / "cache")
    second = _record(tmp_path / "second", tmp_path / "cache")

    assert first == second


def test_a_different_config_records_a_different_activity(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    other = Bundle(tmp_path / "other")

    with _sink(bundle, tmp_path / "cache").activity(
        code_ref="repo@sha", config={"year": 2026}
    ) as activity:
        activity.register(b"payload", type="document", name="data")
    with _sink(other, tmp_path / "cache").activity(
        code_ref="repo@sha", config={"year": 2027}
    ) as activity:
        activity.register(b"payload", type="document", name="data")

    assert bundle.manifest.activity is not None
    assert other.manifest.activity is not None
    assert bundle.manifest.activity.activity_id != other.manifest.activity.activity_id


def _book(sink: RecordingSink) -> object:
    """Draft the one book these sugar tests frame their outputs into."""
    return sink.draft_book("my-dataset", version="v1.0.0", license="MIT")


def test_book_write_records_the_bundle_the_explicit_form_records(tmp_path: Path) -> None:
    """The sugar is sugar. Its bundle must be byte for byte the layered form's bundle."""
    sugar = Bundle(tmp_path / "sugar")
    sugar_sink = _sink(sugar, tmp_path / "cache")
    sugar_book = _book(sugar_sink)
    sugar_book.write("data", b"payload", type="document")
    sugar.write()

    layered = Bundle(tmp_path / "layered")
    layered_sink = _sink(layered, tmp_path / "cache")
    layered_book = _book(layered_sink)
    with layered_sink.activity() as activity:
        resource = activity.register(b"payload", type="document", name="data")
    layered_book.add(resource)
    layered.write()

    assert sugar.manifest_path.read_bytes() == layered.manifest_path.read_bytes()


def test_book_write_defaults_to_the_generic_table_type(tmp_path: Path) -> None:
    """A frame written without a type is catalogued as a table, never as a timeseries."""
    pd = pytest.importorskip("pandas")
    bundle = Bundle(tmp_path / "bundle")
    frame = pd.DataFrame({"region": ["World"], "value": [1.0]})

    _book(_sink(bundle, tmp_path / "cache")).write("data", frame)

    assert [resource.type for resource in bundle.manifest.resources] == ["tabular"]


def test_book_write_and_an_explicit_block_share_one_activity(tmp_path: Path) -> None:
    """Mixing the two forms records one activity, which is all the replay endpoint takes."""
    bundle = Bundle(tmp_path / "bundle")
    sink = _sink(bundle, tmp_path / "cache")
    book = _book(sink)

    with sink.activity(code_ref="repo@sha") as activity:
        first = activity.register(b"first", type="document", name="first")
    book.add(first)
    book.write("second", b"second", type="document")

    assert bundle.manifest.activity is not None
    assert bundle.manifest.activity.code_ref == "repo@sha"
    assert sorted(entry.name for entry in bundle.manifest.book.entries) == ["first", "second"]


def test_a_second_activity_block_says_the_replay_endpoint_takes_one(tmp_path: Path) -> None:
    sink = _sink(Bundle(tmp_path / "bundle"), tmp_path / "cache")
    sink.activity()

    with pytest.raises(BookshelfError, match="one activity"):
        sink.activity()


def test_book_add_refuses_a_handle_that_took_no_name(tmp_path: Path) -> None:
    sink = _sink(Bundle(tmp_path / "bundle"), tmp_path / "cache")
    book = _book(sink)

    with pytest.raises(ValueError, match="registered under a name"):
        book.add(Mock(name="not-a-resource", spec=[]))


def test_a_recorded_book_carries_the_fingerprint_of_the_run_that_generated_it(
    tmp_path: Path,
) -> None:
    """``bookshelf validate`` reads as a complete account, so the book states its processing."""
    bundle = Bundle(tmp_path / "bundle")
    sink = _sink(bundle, tmp_path / "cache")
    book = _book(sink)
    with sink.activity(code_ref="repo@sha", config={"year": 2026}) as activity:
        book.add(activity.register(b"payload", type="document", name="data"))

    _record_processing(bundle)

    assert bundle.manifest.activity is not None
    assert bundle.manifest.book.processing == [("repo@sha", bundle.manifest.activity.config_hash)]


def test_a_book_no_activity_generated_carries_an_empty_fingerprint(tmp_path: Path) -> None:
    """``[]`` is a book with no generating activity, which is not the same as saying nothing."""
    bundle = Bundle(tmp_path / "bundle")
    _book(_sink(bundle, tmp_path / "cache"))

    _record_processing(bundle)

    assert bundle.manifest.book.processing == []
