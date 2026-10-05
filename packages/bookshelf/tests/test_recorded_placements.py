"""Tests for placing a resource the platform already holds in a recorded book."""

import json
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._cli._runtime import EXIT_OK
from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import BookshelfError
from bookshelf._facade import Bookshelf
from bookshelf._generated import models
from bookshelf.publisher.bundle import Bundle, BundleBookEntry, InvalidBundleError
from bookshelf.publisher.preview import PreviewIdentity, upload_preview
from bookshelf.publisher.recipe import load_record_recipe
from bookshelf.publisher.record import _ACTIVE_RECORDING, Build, _RecordingContext, setup
from bookshelf.publisher.recording import RecordingBookshelf
from bookshelf.publisher.replay import replay_bundle
from tests._preview import BASE_URL as PREVIEW_URL
from tests._preview import SHA, PreviewDeployment
from tests._replay import replay_client, replayed
from tests.conftest import BundleFactory

_PLACED_ID = UUID("0193f0f3-0000-7000-8000-000000000001")
_SOURCE = "bookshelf://method/v2.0_e003/hazard-method"

_RECIPE = """\
volume:
  name: cra-release
build:
  notebook: build.py
books:
  - version: "v1.0.0"
    license: MIT
    resources:
      method:
        uri: bookshelf://method/v2.0_e003/hazard-method
"""


@dataclass
class _Entry:
    path: Path
    tracking_id: UUID = _PLACED_ID
    type: models.ResourceType = models.ResourceType.document

    def resource_type(self) -> models.ResourceType:
        return self.type

    def content_hash(self) -> str:
        return "sha256:" + "a" * 64

    def as_path(self) -> Path:
        return self.path


@dataclass
class _Book:
    entries: dict[str, _Entry]

    @property
    def entry_names(self) -> tuple[str, ...]:
        return tuple(self.entries)

    def __getitem__(self, name_in_book: str) -> _Entry:
        return self.entries[name_in_book]

    def lookup(self, volume: str, version: str, *, edition: int | None = None) -> "_Book":
        assert (volume, version, edition) == ("method", "v2.0", 3)
        return self


@pytest.fixture(autouse=True)
def _published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the approved method book through the facade's read path, never the network."""
    held = tmp_path / "held.md"
    held.write_bytes(b"# Method\n")
    monkeypatch.setattr(Bookshelf, "book", _Book({"hazard-method": _Entry(held)}).lookup)


@contextmanager
def _recording(tmp_path: Path) -> Iterator[Build]:
    """Enter a recording context the way run_record does, without executing a notebook."""
    recipe_path = tmp_path / "bookshelf.yaml"
    recipe_path.write_text(textwrap.dedent(_RECIPE), encoding="utf-8")
    recipe = load_record_recipe(recipe_path)
    context = _RecordingContext(
        recipe=recipe,
        resolved=recipe.resolve("v1.0.0"),
        bundle=Bundle(tmp_path / "bundle"),
        recipe_dir=tmp_path,
    )
    token = _ACTIVE_RECORDING.set(context)
    try:
        yield setup()
    finally:
        _ACTIVE_RECORDING.reset(token)
        if context.bookshelf is not None:
            context.bookshelf.close()


def _bundle(build: Build) -> Bundle:
    assert isinstance(build.bs, RecordingBookshelf)
    return build.bs.bundle


def test_a_used_resource_is_placed_under_a_new_name(tmp_path: Path) -> None:
    with _recording(tmp_path) as build:
        response = build.book.attach(build.use("method"), name_in_book="approved-method")
        bundle = _bundle(build)

    assert response.tracking_id == _PLACED_ID
    assert bundle.manifest.resources == []
    assert bundle.manifest.book is not None
    (entry,) = bundle.manifest.book.entries
    assert entry.name == "approved-method"
    assert entry.tracking_id == _PLACED_ID
    assert entry.source == _SOURCE


def test_a_bookshelf_reference_is_placed_without_fetching_it(tmp_path: Path) -> None:
    with _recording(tmp_path) as build:
        build.book.attach("bookshelf://method/v2.0_e003", name_in_book="approved-method")
        bundle = _bundle(build)

    assert bundle.manifest.book is not None
    (entry,) = bundle.manifest.book.entries
    assert entry.tracking_id == _PLACED_ID
    assert entry.source == _SOURCE, "a single-entry book reference is spelled out to its entry"


def test_a_bare_tracking_id_the_bundle_does_not_record_is_placed(tmp_path: Path) -> None:
    with _recording(tmp_path) as build:
        build.book.attach(str(_PLACED_ID), name_in_book="approved-method")
        bundle = _bundle(build)

    assert bundle.manifest.book is not None
    (entry,) = bundle.manifest.book.entries
    assert entry.tracking_id == _PLACED_ID
    assert entry.source is None


def test_something_that_is_neither_an_id_nor_a_reference_is_refused(tmp_path: Path) -> None:
    with _recording(tmp_path) as build, pytest.raises(ValueError, match="neither a tracking id"):
        build.book.attach("hazard-method", name_in_book="approved-method")


def test_a_placement_cannot_take_a_recorded_resource_name(tmp_path: Path) -> None:
    with _recording(tmp_path) as build:
        with build.bs.activity() as activity:
            activity.register(b"summary", type="document", name="summary")
        with pytest.raises(ValueError, match="records a resource of that name"):
            build.book.attach(build.use("method"), name_in_book="summary")


def test_a_resource_cannot_take_a_placed_name(tmp_path: Path) -> None:
    with _recording(tmp_path) as build:
        build.book.attach(build.use("method"), name_in_book="summary")
        with pytest.raises(ValueError, match="already a placed entry"):
            build.book.write("summary", b"summary", type="document")


def test_a_placement_cannot_repeat_an_entry_name(tmp_path: Path) -> None:
    with _recording(tmp_path) as build:
        build.book.attach(build.use("method"), name_in_book="approved-method")
        with pytest.raises(ValueError, match="already used in this book"):
            build.book.attach(_SOURCE, name_in_book="approved-method")


def test_a_resource_cannot_be_placed_twice(tmp_path: Path) -> None:
    """The platform refuses a repeated placement, so it is caught before anything uploads."""
    with _recording(tmp_path) as build:
        build.book.attach(build.use("method"), name_in_book="approved-method")
        with pytest.raises(ValueError, match="already placed in this book"):
            build.book.attach(_SOURCE, name_in_book="method-again")


def test_an_unpublished_reference_names_the_placement(tmp_path: Path) -> None:
    with _recording(tmp_path) as build, pytest.raises(BookshelfError) as excinfo:
        build.book.attach("bookshelf://method/v2.0_e003/missing", name_in_book="approved-method")

    message = str(excinfo.value)
    assert message.startswith("a placement names bookshelf://method/v2.0_e003/missing")
    assert "resource 'bookshelf://" not in message


def test_a_placement_adds_no_lineage(tmp_path: Path) -> None:
    with _recording(tmp_path) as build:
        build.book.attach(build.use("method"), name_in_book="approved-method")
        build.book.write("summary", b"summary", type="document")
        bundle = _bundle(build)

    (summary,) = bundle.manifest.resources
    assert summary.used == []
    assert summary.used_digests == []


def _placed(make_bundle: BundleFactory) -> Bundle:
    bundle = make_bundle()
    bundle.add_book_entry(name="approved-method", tracking_id=_PLACED_ID, source=_SOURCE)
    bundle.write()
    return bundle


def test_a_bundle_with_a_placement_validates(make_bundle: BundleFactory) -> None:
    Bundle.read_validated(_placed(make_bundle).root)


def test_a_placement_survives_a_round_trip(make_bundle: BundleFactory) -> None:
    framing = Bundle.read(_placed(make_bundle).root).require_framing()

    placed = framing.entries[-1]
    assert (placed.tracking_id, placed.source) == (_PLACED_ID, _SOURCE)


def test_validate_refuses_a_placement_named_like_a_recorded_resource(
    make_bundle: BundleFactory,
) -> None:
    bundle = _placed(make_bundle)
    framing = bundle.require_framing()
    framing.entries[-1].name = "entry-0"

    with pytest.raises(InvalidBundleError, match="records a resource of that name"):
        bundle.validate()


def test_validate_refuses_a_resource_placed_twice(make_bundle: BundleFactory) -> None:
    bundle = _placed(make_bundle)
    bundle.require_framing().entries.append(
        BundleBookEntry(name="method-again", tracking_id=_PLACED_ID)
    )

    with pytest.raises(InvalidBundleError, match="another entry already places"):
        bundle.validate()


def test_replay_sends_the_placed_tracking_id(make_bundle: BundleFactory) -> None:
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as bs:
        replay_bundle(_placed(make_bundle), bs)

    entries = replayed(recorded)["book"]["entries"]
    assert entries == [
        {"name": "entry-0"},
        {"name": "approved-method", "tracking_id": str(_PLACED_ID)},
    ]


def test_the_preview_manifest_carries_the_placed_tracking_id(make_bundle: BundleFactory) -> None:
    deployment = PreviewDeployment()
    identity = PreviewIdentity(
        repository="climate-resource/feedstock",
        pr_number=7,
        pr_url="https://github.com/climate-resource/feedstock/pull/7",
        head_sha=SHA,
        main_sha=SHA,
        candidate_tree=SHA,
        run_id="42",
    )

    with BookshelfClient(PREVIEW_URL, auth=None, transport=deployment.transport()) as client:
        outcome = upload_preview([_placed(make_bundle).root], client, identity)

    assert outcome.refused == {}
    (attached,) = deployment.sent("/v1.0.0")
    assert attached["manifest"]["entries"][-1] == {
        "name": "approved-method",
        "tracking_id": str(_PLACED_ID),
    }
    assert [file["name"] for file in attached["resources"]] == ["entry-0"]


def test_validate_lists_every_placement(make_bundle: BundleFactory) -> None:
    result = CliRunner().invoke(app, ["validate", str(_placed(make_bundle).root), "--json"])

    assert result.exit_code == EXIT_OK
    assert json.loads(result.stdout)["placements"] == [
        {"name": "approved-method", "tracking_id": str(_PLACED_ID), "source": _SOURCE}
    ]
