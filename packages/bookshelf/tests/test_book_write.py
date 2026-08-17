"""Tests for ``book.write`` and ``book.add``, the sugar over register-then-attach.

The headline property is that the sugar is only sugar.
A bundle recorded through ``book.write`` must be the bundle the layered form records,
because anything else would make the convenient path and the explicit path diverge
in what they publish.
"""

import inspect
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest

from bookshelf._core.client import BookshelfClient
from bookshelf._produce.books import AsyncDraftBook, DraftBook
from bookshelf.cache import ContentCache
from bookshelf.publisher.bundle import Bundle, BundleManifest
from bookshelf.publisher.recording import WRITE_ACTIVITY_KIND, RecordingSink

PARAMETERS = {"version": "v2.7"}

PINNED_ACTIVITY_ID = UUID("00000000-0000-7000-8000-000000000000")
PINNED_CODE_REF = "https://example.invalid/test@0"
PINNED_RUNNER = "pytest"


def _sink(bundle: Bundle, cache_path: Path, **kwargs: object) -> RecordingSink:
    return RecordingSink(
        bundle,
        Mock(spec=BookshelfClient),
        ContentCache(cache_path),
        **kwargs,  # type: ignore[arg-type]
    )


def _book(sink: RecordingSink) -> object:
    return sink.draft_book("my-dataset", version="v1.0.0", license="MIT")


def _pinned(manifest: BundleManifest) -> bytes:
    """Serialise a manifest with only the genuinely per-run fields pinned.

    They are pinned rather than dropped, so a change to any of them still fails the comparison.
    """
    copy = manifest.model_copy(deep=True)
    assert copy.activity is not None
    copy.activity.activity_id = PINNED_ACTIVITY_ID
    copy.activity.code_ref = PINNED_CODE_REF
    copy.activity.runner = PINNED_RUNNER
    return copy.model_dump_json(exclude_none=True).encode()


def test_book_write_records_what_the_explicit_form_records(tmp_path: Path) -> None:
    """Case 1: the headline equivalence property, byte for byte."""
    sugar = Bundle(tmp_path / "sugar")
    sugar_sink = _sink(sugar, tmp_path / "cache", parameters=PARAMETERS)
    sugar_book = _book(sugar_sink)
    raw = sugar_sink.register_external(
        type="tabular", uri="https://example.invalid/raw", name="raw"
    )
    sugar_book.write("by_country", b"payload", type="document", used=[raw])

    layered = Bundle(tmp_path / "layered")
    layered_sink = _sink(layered, tmp_path / "cache", parameters=PARAMETERS)
    layered_book = _book(layered_sink)
    layered_raw = layered_sink.register_external(
        type="tabular", uri="https://example.invalid/raw", name="raw"
    )
    with layered_sink.activity(kind=WRITE_ACTIVITY_KIND, config=PARAMETERS) as act:
        country = act.register(b"payload", type="document", name="by_country", used=[layered_raw])
    layered_book.attach(country, name_in_book="by_country")

    assert _pinned(sugar.manifest) == _pinned(layered.manifest)


def test_the_implicit_activity_kind_is_fixed(tmp_path: Path) -> None:
    """Case 2: the kind lands in the manifest, so it is pinned rather than defaulted."""
    bundle = Bundle(tmp_path / "bundle")
    _book(_sink(bundle, tmp_path / "cache")).write("data", b"payload", type="document")

    assert bundle.manifest.activity is not None
    assert bundle.manifest.activity.kind == "process"


def test_the_implicit_activity_config_is_seeded_from_the_cli_parameters(tmp_path: Path) -> None:
    """Case 3: the recorded parameters carry what -p stated, and nothing else."""
    first = Bundle(tmp_path / "first")
    _book(_sink(first, tmp_path / "cache", parameters=PARAMETERS)).write(
        "data", b"payload", type="document"
    )
    second = Bundle(tmp_path / "second")
    _book(_sink(second, tmp_path / "cache", parameters=PARAMETERS)).write(
        "data", b"payload", type="document"
    )

    assert first.manifest.activity is not None
    assert first.manifest.activity.parameters == PARAMETERS
    assert _pinned(first.manifest) == _pinned(second.manifest)


def test_a_different_parameter_records_a_different_fingerprint(tmp_path: Path) -> None:
    """The config hash is what a reissue turns on, so it must move when a parameter moves."""
    first = Bundle(tmp_path / "first")
    _book(_sink(first, tmp_path / "cache", parameters={"version": "v2.7"})).write(
        "data", b"payload", type="document"
    )
    second = Bundle(tmp_path / "second")
    _book(_sink(second, tmp_path / "cache", parameters={"version": "v2.8"})).write(
        "data", b"payload", type="document"
    )

    assert first.manifest.activity is not None
    assert second.manifest.activity is not None
    assert first.manifest.activity.config_hash != second.manifest.activity.config_hash


def test_many_writes_share_one_implicit_activity(tmp_path: Path) -> None:
    """Case 4: a recorded bundle carries one activity, and every write is attributed to it."""
    bundle = Bundle(tmp_path / "bundle")
    book = _book(_sink(bundle, tmp_path / "cache"))

    book.write("first", b"first", type="document")
    book.write("second", b"second", type="document")

    assert bundle.manifest.activity is not None
    assert sorted(entry.name for entry in bundle.manifest.book.entries) == ["first", "second"]


def test_book_write_returns_a_handle_that_cites_as_lineage(tmp_path: Path) -> None:
    """Case 5: the handle write hands back is usable as an input to the next write."""
    bundle = Bundle(tmp_path / "bundle")
    book = _book(_sink(bundle, tmp_path / "cache"))

    first = book.write("a", b"first", type="document")
    book.write("b", b"second", type="document", used=[first])

    recorded = {resource.name: resource.used for resource in bundle.manifest.resources}
    assert recorded["b"] == ["a"]


def test_book_add_attaches_by_each_resources_own_name(tmp_path: Path) -> None:
    """Case 6: add takes no names, because each handle already knows the one it took."""
    bundle = Bundle(tmp_path / "bundle")
    sink = _sink(bundle, tmp_path / "cache")
    book = _book(sink)

    with sink.activity() as act:
        countries = act.register(b"countries", type="document", name="by_country")
        regions = act.register(b"regions", type="document", name="by_region")
    book.add(countries, regions)

    assert sorted(entry.name for entry in bundle.manifest.book.entries) == [
        "by_country",
        "by_region",
    ]


def test_book_add_registers_nothing(tmp_path: Path) -> None:
    """Case 7: add is an attachment, so it must not put a second copy in the manifest."""
    bundle = Bundle(tmp_path / "bundle")
    sink = _sink(bundle, tmp_path / "cache")
    book = _book(sink)
    with sink.activity() as act:
        resource = act.register(b"payload", type="document", name="data")
    before = len(bundle.manifest.resources)

    book.add(resource)

    assert len(bundle.manifest.resources) == before


def test_the_async_twin_takes_the_same_arguments() -> None:
    """Case 8: the two surfaces are one API, so ``write`` and ``add`` must take the same shape.

    ``test_sync_async_parity`` now carries the draft books, which asserts this across every
    member. This case names the two the sugar added, so their loss is reported here too.
    """
    for name in ("write", "add"):
        sync = inspect.signature(getattr(DraftBook, name))
        twin = inspect.signature(getattr(AsyncDraftBook, name))

        assert list(sync.parameters) == list(twin.parameters), f"{name} signatures diverged"
        assert [p.default for p in sync.parameters.values()] == [
            p.default for p in twin.parameters.values()
        ], f"{name} defaults diverged"


def test_book_write_defaults_to_the_generic_table_type(tmp_path: Path) -> None:
    """A frame written without a type is catalogued as a table, never as a timeseries."""
    pd = pytest.importorskip("pandas")
    bundle = Bundle(tmp_path / "bundle")
    frame = pd.DataFrame({"region": ["World"], "value": [1.0]})

    _book(_sink(bundle, tmp_path / "cache")).write("data", frame)

    assert [resource.type for resource in bundle.manifest.resources] == ["tabular"]


def test_the_sugar_and_an_explicit_block_share_one_activity(tmp_path: Path) -> None:
    """A build may mix the two forms, and still record the one activity replay accepts."""
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


def test_book_add_refuses_a_handle_that_took_no_name(tmp_path: Path) -> None:
    """add attaches by the handle's own name, so a nameless handle has nothing to attach under."""
    book = _book(_sink(Bundle(tmp_path / "bundle"), tmp_path / "cache"))

    with pytest.raises(ValueError, match="registered under a name"):
        book.add(Mock(name="not-a-resource", spec=[]))
