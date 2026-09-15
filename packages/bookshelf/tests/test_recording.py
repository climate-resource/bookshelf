"""Tests for the bundle-backed producer recording adapter."""

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import polars as pl
import pytest
from matplotlib.figure import Figure

from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.serialise import figure_svg, serialise
from bookshelf._produce.types import RegisterItem
from bookshelf.cache import ContentCache
from bookshelf.publisher.bundle import Bundle, companion_filename, resource_filename
from bookshelf.publisher.record import _record_processing
from bookshelf.publisher.recording import RecordedDraftBook, RecordingActivity, RecordingSink


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


def test_a_bare_tracking_id_the_bundle_does_not_record_says_what_to_pass(tmp_path: Path) -> None:
    """An id alone carries no digest, so there is nothing for the citation to travel under."""
    bundle = Bundle(tmp_path / "bundle")
    stranger = uuid.UUID("0193f0f3-0000-7000-8000-0000000000ff")

    with (
        _activity(bundle, tmp_path / "cache") as activity,
        pytest.raises(ValueError) as excinfo,
    ):
        activity.register(b"derived", type="tabular", name="derived", used=[stranger])

    message = str(excinfo.value)
    assert "this bundle does not record" in message
    assert "build.use()" in message


def test_an_input_carrying_a_citable_digest_is_recorded_as_one(tmp_path: Path) -> None:
    """The recipe resolved the input in-organisation, so the bundle cites the bytes it holds."""
    bundle = Bundle(tmp_path / "bundle")
    digest = "sha256:" + "c" * 64
    upload = SimpleNamespace(
        tracking_id=uuid.UUID("0193f0f3-0000-7000-8000-0000000000fe"),
        citable_hash=digest,
    )

    with _activity(bundle, tmp_path / "cache") as activity:
        activity.register(b"derived", type="tabular", name="derived", used=[upload])

    recorded = bundle.manifest.resources[0]
    assert recorded.used == []
    assert recorded.used_digests == [digest]


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


def _book(sink: RecordingSink) -> RecordedDraftBook:
    """Draft the one book these sugar tests frame their outputs into."""
    return sink.draft_book("my-dataset", version="v1.0.0", license="MIT")


def test_a_second_activity_block_says_the_replay_endpoint_takes_one(tmp_path: Path) -> None:
    sink = _sink(Bundle(tmp_path / "bundle"), tmp_path / "cache")
    sink.activity()

    with pytest.raises(BookshelfError, match="one activity"):
        sink.activity()


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


def _figure() -> Figure:
    fig = Figure()
    fig.add_subplot().bar(["a", "b"], [1.0, 2.0])
    return fig


def test_a_figure_records_its_plotted_values_before_it(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    book = _book(_sink(bundle, tmp_path / "cache"))

    book.write(
        "fig", _figure(), type="figure", data=pl.DataFrame({"x": ["a", "b"], "y": [1.0, 2.0]})
    )
    book.publish()

    values, figure = bundle.manifest.resources
    assert (values.name, values.type, values.format) == ("fig-data", "tabular", "parquet")
    assert (figure.name, figure.type, figure.format) == ("fig", "figure", "png")
    assert figure.used == ["fig-data"]
    assert [entry.name for entry in bundle.require_framing().entries] == ["fig-data", "fig"]
    assert (bundle.resources_dir / resource_filename(figure.hash, "figure")).suffix == ".png"
    assert (bundle.resources_dir / resource_filename(figure.hash, "figure")).exists()
    bundle.validate()


def test_the_plotted_values_are_not_cited_by_later_resources(tmp_path: Path) -> None:
    """The values are an output of the build, so only the figure was drawn from them."""
    bundle = Bundle(tmp_path / "bundle")
    sink = _sink(bundle, tmp_path / "cache")
    book = _book(sink)
    raw = sink.writing_activity().register(b"raw", type="tabular", name="raw")

    book.write("fig", _figure(), type="figure", data=pl.DataFrame({"y": [1.0]}), used=[raw])
    book.write("later", b"later", type="document")
    sink.record_document(b"notebook", name="notebook", metadata={})

    recorded = {resource.name: resource.used for resource in bundle.manifest.resources}
    assert recorded["fig-data"] == ["raw"]
    assert recorded["fig"] == ["raw", "fig-data"]
    assert recorded["later"] == ["raw"]
    assert recorded["notebook"] == ["raw"]


def test_plotted_values_for_anything_but_a_figure_record_nothing(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    book = _book(_sink(bundle, tmp_path / "cache"))

    with pytest.raises(ValueError, match="figure"):
        book.write(
            "table", pl.DataFrame({"y": [1.0]}), type="tabular", data=pl.DataFrame({"y": [1.0]})
        )

    assert bundle.manifest.resources == []


def test_a_figure_records_its_words_and_its_plotted_values_carry_none(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    book = _book(_sink(bundle, tmp_path / "cache"))

    book.write(
        "fig",
        _figure(),
        type="figure",
        data=pl.DataFrame({"y": [1.0, 2.0]}),
        caption="Two bars.",
        alt_text="A bar chart with two bars, the second twice the height of the first.",
    )

    values, figure = bundle.manifest.resources
    assert (figure.caption, figure.alt_text) == (
        "Two bars.",
        "A bar chart with two bars, the second twice the height of the first.",
    )
    assert (values.caption, values.alt_text) == (None, None)


def test_a_public_figure_without_alt_text_records_nothing(tmp_path: Path) -> None:
    """The check runs before the plotted values are written, so a refused figure leaves no sidecar."""
    bundle = Bundle(tmp_path / "bundle")
    sink = _sink(bundle, tmp_path / "cache")
    book = sink.draft_book("my-dataset", version="v1.0.0", license="MIT", visibility="public")

    with pytest.raises(ValueError, match="public figure with no alt text"):
        book.write("fig", _figure(), type="figure", data=pl.DataFrame({"y": [1.0]}))

    assert bundle.manifest.resources == []


def test_a_figure_inherits_the_public_tier_it_is_checked_against(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    sink = _sink(bundle, tmp_path / "cache")
    book = sink.draft_book("my-dataset", version="v1.0.0", license="MIT", visibility="public")

    with pytest.raises(ValueError, match="public figure with no alt text"):
        book.write("fig", _figure(), type="figure")
    book.write("fig", _figure(), type="figure", alt_text="An empty axis.")
    book.write("org-fig", _figure(), type="figure", visibility="org")

    assert [resource.name for resource in bundle.manifest.resources] == ["fig", "org-fig"]


def test_a_batched_public_figure_without_alt_text_records_nothing(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    activity = _activity(bundle, tmp_path / "cache")
    activity.default_visibility = models.Visibility.public

    with activity, pytest.raises(ValueError, match="public figure with no alt text"):
        activity.register_many(
            [
                RegisterItem(obj=b"table", type="tabular", name="table"),
                RegisterItem(obj=_figure(), type="figure", name="fig"),
            ]
        )

    assert bundle.manifest.resources == []


def test_a_matplotlib_figure_records_its_svg_companion(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    book = _book(_sink(bundle, tmp_path / "cache"))
    fig = _figure()

    book.write("fig", fig, type="figure", data=pl.DataFrame({"y": [1.0, 2.0]}))
    book.publish()

    values, figure = bundle.manifest.resources
    assert figure.svg_hash is not None
    companion = bundle.resources_dir / companion_filename(figure.svg_hash)
    assert companion.suffix == ".svg"
    assert companion.read_bytes() == figure_svg(fig)
    assert values.svg_hash is None
    bundle.validate()


def test_png_bytes_record_no_svg_companion(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    book = _book(_sink(bundle, tmp_path / "cache"))
    png = serialise(_figure(), type="figure").data

    book.write("fig", png, type="figure")
    book.publish()

    (figure,) = bundle.manifest.resources
    assert figure.svg_hash is None
    assert [path.suffix for path in bundle.resources_dir.iterdir()] == [".png"]
