"""Tests for resolving declared resources: fetch, verify, cache and register."""

import hashlib
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import httpx
import pytest

from bookshelf._core.errors import BookshelfError, NotFoundError
from bookshelf._generated import models
from bookshelf._produce.books import DraftBook
from bookshelf.facade import Bookshelf
from bookshelf.publisher import resource as resource_module
from bookshelf.publisher.bundle import Bundle, BundleResource
from bookshelf.publisher.recipe import load_record_recipe
from bookshelf.publisher.record import (
    _ACTIVE_RECORDING,
    Build,
    _RecordingContext,
    setup,
)
from bookshelf.publisher.recording import RecordingBookshelf

_VERSION = "v1.0.0"
_PAYLOAD = b"gas,year,value\nco2,2023,1.0\n"
_SHA256 = hashlib.sha256(_PAYLOAD).hexdigest()

_RECIPE = """\
volume:
  name: my-dataset
build:
  notebook: build.py
books:
  - version: "v1.0.0"
    license: MIT
{version_body}
"""

_URI_VERSION = f"""\
doi: 10.5281/zenodo.13752654
resources:
  raw:
    type: tabular
    uri: https://example.invalid/raw.csv
    sha256: {_SHA256}
"""

_PATH_VERSION = """\
resources:
  raw:
    type: tabular
    path: data/raw.csv
"""

_REFERENCE_VERSION = """\
resources:
  raw:
    uri: bookshelf://primap-hist/v2.7_e002/by_country
"""

_PUBLISHED_ID = UUID("0193f0f3-0000-7000-8000-000000000001")


def _write_recipe(tmp_path: Path, version_body: str) -> Path:
    """Write a recipe whose one version carries ``version_body`` verbatim."""
    body = textwrap.indent(textwrap.dedent(version_body), "    ")
    path = tmp_path / "bookshelf.yaml"
    path.write_text(_RECIPE.format(version_body=body), encoding="utf-8")
    return path


def _write_data(tmp_path: Path) -> Path:
    """Check the payload in beside the recipe, where a path resource expects it."""
    data = tmp_path / "data" / "raw.csv"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_bytes(_PAYLOAD)
    return data


@contextmanager
def _recording(recipe_path: Path, bundle_path: Path) -> Iterator[None]:
    """Enter a recording context the way run_record does, without executing a notebook."""
    recipe = load_record_recipe(recipe_path)
    context = _RecordingContext(
        recipe=recipe,
        resolved=recipe.resolve(_VERSION),
        bundle=Bundle(bundle_path),
        recipe_dir=recipe_path.parent,
    )
    token = _ACTIVE_RECORDING.set(context)
    try:
        yield
    finally:
        _ACTIVE_RECORDING.reset(token)
        if context.bookshelf is not None:
            context.bookshelf.close()


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test's downloads out of the user's real content cache."""
    monkeypatch.setenv("BOOKSHELF_CACHE_DIR", str(tmp_path / "content-cache"))


@dataclass
class _Server:
    """Canned bytes served through a mock transport, counting every request."""

    payload: bytes = _PAYLOAD
    requests: list[httpx.Request] = field(default_factory=list)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> _Server:
    """Rebind the download client so a fetch reaches canned bytes, never the network."""
    served = _Server()

    def handler(request: httpx.Request) -> httpx.Response:
        served.requests.append(request)
        return httpx.Response(200, content=served.payload)

    def client() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)

    monkeypatch.setattr(resource_module, "_download_client", client)
    return served


def _pointers(bs: RecordingBookshelf) -> list[BundleResource]:
    return [r for r in bs.bundle.manifest.resources if r.kind == "pointer"]


@dataclass
class _PublishedEntry:
    """One entry of a published book, as the consuming facade hands it over."""

    path: Path
    tracking_id: UUID = _PUBLISHED_ID
    type: models.ResourceType = models.ResourceType.timeseries

    @property
    def metadata(self) -> SimpleNamespace:
        return SimpleNamespace(hash=f"sha256:{_SHA256}")

    def as_path(self) -> Path:
        return self.path


@dataclass
class _PublishedBook:
    """A published book, plus a record of the coordinate it was looked up by."""

    entries: dict[str, _PublishedEntry]
    looked_up: list[tuple[str, str, int | None]] = field(default_factory=list)

    @property
    def entry_names(self) -> tuple[str, ...]:
        return tuple(self.entries)

    def __getitem__(self, name_in_book: str) -> _PublishedEntry:
        try:
            return self.entries[name_in_book]
        except KeyError:
            available = ", ".join(sorted(self.entries)) or "(none)"
            raise KeyError(f"has no entry {name_in_book!r}, available: {available}") from None

    def lookup(self, volume: str, version: str, *, edition: int | None = None) -> "_PublishedBook":
        self.looked_up.append((volume, version, edition))
        return self


@pytest.fixture
def published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _PublishedBook:
    """Serve one published book through the facade's read path, never the network."""
    cached = tmp_path / "published" / "by_country.csv"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(_PAYLOAD)
    book = _PublishedBook({"by_country": _PublishedEntry(cached)})
    monkeypatch.setattr(Bookshelf, "book", book.lookup)
    return book


def test_a_uri_resource_fetches_once_and_reads_back(tmp_path: Path, server: _Server) -> None:
    with _recording(_write_recipe(tmp_path, _URI_VERSION), tmp_path / "bundle"):
        build = setup()
        raw = build.use("raw")

        assert raw.name == "raw"
        assert raw.path.read_bytes() == _PAYLOAD
        assert raw.hash == f"sha256:{_SHA256}"
        assert raw.path.parent == tmp_path / "content-cache"
    assert len(server.requests) == 1


def test_a_second_resolve_is_served_from_the_cache(tmp_path: Path, server: _Server) -> None:
    """The declared digest is the cache key, so a hit performs no HTTP request at all."""
    with _recording(_write_recipe(tmp_path, _URI_VERSION), tmp_path / "bundle"):
        build = setup()
        first = build.use("raw")
        again = build.use("raw")

    assert len(server.requests) == 1
    assert again.path == first.path


def test_a_digest_mismatch_is_a_hard_failure(tmp_path: Path, server: _Server) -> None:
    """A mismatch names both digests, retries nothing, and commits nothing to the cache."""
    server.payload = b"tampered"

    with _recording(_write_recipe(tmp_path, _URI_VERSION), tmp_path / "bundle"):
        build = setup()
        with pytest.raises(BookshelfError) as excinfo:
            build.use("raw")

    message = str(excinfo.value)
    assert _SHA256 in message
    assert hashlib.sha256(b"tampered").hexdigest() in message
    assert len(server.requests) == 1
    assert list((tmp_path / "content-cache").iterdir()) == []


def test_a_path_resource_resolves_and_computes_its_digest(tmp_path: Path) -> None:
    recipe = _write_recipe(tmp_path, _PATH_VERSION)
    data = _write_data(tmp_path)

    with _recording(recipe, tmp_path / "bundle"):
        build = setup()
        raw = build.use("raw")

    assert raw.path == data.resolve()
    assert raw.hash == f"sha256:{_SHA256}"


def test_a_path_resource_records_its_bytes_rather_than_a_pointer(tmp_path: Path) -> None:
    """A repository path is no address the platform can fetch from, so the bytes travel.

    A pointer at ``data/raw.csv`` is what publishing rejects,
    because the platform would have to dereference it against its own filesystem.
    """
    recipe = _write_recipe(tmp_path, _PATH_VERSION)
    _write_data(tmp_path)
    bundle_path = tmp_path / "bundle"

    with _recording(recipe, bundle_path):
        build = setup()
        build.use("raw")
        recorded = _written_resource(build.bs, bundle_path, "raw")

    assert recorded.kind == "managed"
    assert recorded.external_uri is None
    assert recorded.generated is False
    assert (bundle_path / "resources").exists()


def test_a_checked_in_input_records_where_it_is_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bytes are re-hosted, so the link back to the repository is what is left."""
    sha = "b9aa2996d890d16691d9978ec4f1772f5e51b0f1"
    monkeypatch.setattr(
        "bookshelf.publisher.recording.derive_code_ref",
        lambda: f"git@github.com:climate-resource/feedstock.git@{sha}",
    )
    recipe = _write_recipe(tmp_path, _PATH_VERSION)
    _write_data(tmp_path)
    bundle_path = tmp_path / "bundle"

    with _recording(recipe, bundle_path):
        build = setup()
        build.use("raw")
        recorded = _written_resource(build.bs, bundle_path, "raw")

    assert recorded.metadata["source_url"] == (
        f"https://github.com/climate-resource/feedstock/blob/{sha}/data/raw.csv"
    )


def test_a_checked_in_input_without_a_derivable_commit_still_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout git cannot read is a missing link, not a failed build."""

    def _refuse() -> str:
        raise BookshelfError("no repository here")

    monkeypatch.setattr("bookshelf.publisher.recording.derive_code_ref", _refuse)
    recipe = _write_recipe(tmp_path, _PATH_VERSION)
    _write_data(tmp_path)
    bundle_path = tmp_path / "bundle"

    with _recording(recipe, bundle_path):
        build = setup()
        raw = build.use("raw")
        recorded = _written_resource(build.bs, bundle_path, "raw")

    assert raw.hash == f"sha256:{_SHA256}"
    assert "source_url" not in recorded.metadata


def test_a_path_resource_is_recipe_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same recipe resolves the same file wherever the process is run from."""
    recipe = _write_recipe(tmp_path, _PATH_VERSION)
    data = _write_data(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    with _recording(recipe, tmp_path / "bundle"):
        build = setup()
        raw = build.use("raw")

    assert raw.path == data.resolve()


def test_a_path_resource_that_resolves_outside_the_recipe_is_rejected(tmp_path: Path) -> None:
    """The loader rejects a ``..`` path, so a symlink is what still reaches this guard.

    Following the link is what makes the check a real one.
    Comparing the declared path would pass a link that lands anywhere on the machine.
    """
    recipe = _write_recipe(tmp_path, _PATH_VERSION)
    outside = tmp_path.parent / "outside.csv"
    outside.write_bytes(b"not mine to read")
    link = tmp_path / "data" / "raw.csv"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)

    with _recording(recipe, tmp_path / "bundle"):
        build = setup()
        with pytest.raises(BookshelfError, match="resolves outside the recipe directory"):
            build.use("raw")
        assert _pointers(build.bs) == []


def test_a_missing_path_resource_names_the_resolved_path(tmp_path: Path) -> None:
    recipe = _write_recipe(tmp_path, _PATH_VERSION)

    with _recording(recipe, tmp_path / "bundle"):
        build = setup()
        with pytest.raises(BookshelfError) as excinfo:
            build.use("raw")

    assert str((tmp_path / "data" / "raw.csv").resolve()) in str(excinfo.value)


def test_an_unknown_resource_name_lists_the_declared_ones(tmp_path: Path, server: _Server) -> None:
    with _recording(_write_recipe(tmp_path, _URI_VERSION), tmp_path / "bundle"):
        build = setup()
        with pytest.raises(BookshelfError) as excinfo:
            build.use("nope")

    message = str(excinfo.value)
    assert "'nope'" in message
    assert "'raw'" in message
    assert server.requests == []


def test_a_version_without_resources_reports_the_unknown_name(tmp_path: Path) -> None:
    """Declaring no resources is legal, so resolving one fails by name rather than crashing."""
    with _recording(_write_recipe(tmp_path, ""), tmp_path / "bundle"):
        build = setup()
        with pytest.raises(BookshelfError) as excinfo:
            build.use("raw")

    message = str(excinfo.value)
    assert "declares no resource 'raw'" in message
    assert "declares no resources" in message


def test_a_bookshelf_resource_resolves_to_the_published_resource(
    tmp_path: Path, published: _PublishedBook
) -> None:
    """The reference is a lookup, so the tracking id is the platform's rather than a new one."""
    with _recording(_write_recipe(tmp_path, _REFERENCE_VERSION), tmp_path / "bundle"):
        build = setup()
        raw = build.use("raw")

        assert raw.tracking_id == _PUBLISHED_ID
        assert raw.path.read_bytes() == _PAYLOAD
        assert raw.hash == f"sha256:{_SHA256}"
        assert _pointers(build.bs) == []
    assert published.looked_up == [("primap-hist", "v2.7", 2)]


@pytest.mark.xfail(
    raises=ValueError,
    strict=True,
    reason="A replay cites its inputs by name against its own resources, "
    "so a published input has no coordinate to travel under and is refused at record time. "
    "A feedstock built on another book needs this, so the capability loss is a regression "
    "rather than the contract we want.",
)
def test_a_bookshelf_resource_is_cited_as_lineage_without_being_registered(
    tmp_path: Path, published: _PublishedBook
) -> None:
    """The derived resource cites the published original it was built from."""
    with _recording(_write_recipe(tmp_path, _REFERENCE_VERSION), tmp_path / "bundle"):
        build = setup()
        raw = build.use("raw")
        with build.bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular", name="derived", used=[raw])
        recorded = {resource.name: resource for resource in build.bs.bundle.manifest.resources}

    assert recorded["derived"].used == ["raw"]


def test_a_bookshelf_reference_without_an_entry_resolves_a_single_entry_book(
    tmp_path: Path, published: _PublishedBook
) -> None:
    body = "resources:\n  raw:\n    uri: bookshelf://primap-hist/v2.7_e002\n"

    with _recording(_write_recipe(tmp_path, body), tmp_path / "bundle"):
        build = setup()

        assert build.use("raw").tracking_id == _PUBLISHED_ID


def test_a_bookshelf_reference_without_an_entry_names_the_entries_it_could_take(
    tmp_path: Path, published: _PublishedBook
) -> None:
    published.entries["by_gas"] = published.entries["by_country"]
    body = "resources:\n  raw:\n    uri: bookshelf://primap-hist/v2.7_e002\n"

    with _recording(_write_recipe(tmp_path, body), tmp_path / "bundle"):
        build = setup()
        with pytest.raises(BookshelfError) as excinfo:
            build.use("raw")

    message = str(excinfo.value)
    assert "'by_country'" in message
    assert "'by_gas'" in message


def test_a_bookshelf_reference_to_an_entry_the_book_lacks_is_rejected(
    tmp_path: Path, published: _PublishedBook
) -> None:
    body = "resources:\n  raw:\n    uri: bookshelf://primap-hist/v2.7_e002/by_gas\n"

    with _recording(_write_recipe(tmp_path, body), tmp_path / "bundle"):
        build = setup()
        with pytest.raises(BookshelfError, match="has no entry 'by_gas'"):
            build.use("raw")


def test_a_bookshelf_reference_to_an_unpublished_book_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(volume: str, version: str, *, edition: int | None = None) -> None:
        raise NotFoundError("no such book", status_code=404)

    monkeypatch.setattr(Bookshelf, "book", staticmethod(missing))

    with _recording(_write_recipe(tmp_path, _REFERENCE_VERSION), tmp_path / "bundle"):
        build = setup()
        with pytest.raises(BookshelfError, match="which is not published"):
            build.use("raw")


def test_a_declared_type_that_the_published_resource_contradicts_is_rejected(
    tmp_path: Path, published: _PublishedBook
) -> None:
    """A stated type is checked, because reading the wrong shape fails later and less clearly."""
    body = (
        "resources:\n  raw:\n"
        "    type: tabular\n"
        "    uri: bookshelf://primap-hist/v2.7_e002/by_country\n"
    )

    with _recording(_write_recipe(tmp_path, body), tmp_path / "bundle"):
        build = setup()
        with pytest.raises(BookshelfError, match="declares type tabular"):
            build.use("raw")


def test_a_direct_build_refuses_to_resolve_a_resource() -> None:
    """A build against the API has no recipe, so there is nothing to resolve a name against."""
    with Bookshelf() as bs:
        build = Build(bs, MagicMock(spec=DraftBook))
        with pytest.raises(BookshelfError, match="no active recording"):
            build.use("raw")


def _written_pointers(bs: RecordingBookshelf, bundle_path: Path) -> list[BundleResource]:
    """Write the bundle and read its pointers back, so the assertion is on the manifest on disk."""
    bs.bundle.write()
    return [r for r in Bundle.read(bundle_path).manifest.resources if r.kind == "pointer"]


def _written_resource(bs: RecordingBookshelf, bundle_path: Path, name: str) -> BundleResource:
    """Write the bundle and read one resource back, so the assertion is on the manifest on disk."""
    bs.bundle.write()
    return next(r for r in Bundle.read(bundle_path).manifest.resources if r.name == name)


def test_a_version_doi_lands_on_the_recorded_pointer(tmp_path: Path, server: _Server) -> None:
    bundle_path = tmp_path / "bundle"
    with _recording(_write_recipe(tmp_path, _URI_VERSION), bundle_path):
        build = setup()
        build.use("raw")
        pointer = _written_pointers(build.bs, bundle_path)[0]

    assert pointer.type == "tabular"
    assert pointer.hash == f"sha256:{_SHA256}"
    assert pointer.external_uri == "https://example.invalid/raw.csv"
    assert pointer.metadata == {"doi": "10.5281/zenodo.13752654"}


def test_a_version_without_a_doi_records_no_doi_key(tmp_path: Path) -> None:
    recipe = _write_recipe(tmp_path, _PATH_VERSION)
    _write_data(tmp_path)
    bundle_path = tmp_path / "bundle"

    with _recording(recipe, bundle_path):
        build = setup()
        build.use("raw")
        recorded = _written_resource(build.bs, bundle_path, "raw")

    assert "doi" not in recorded.metadata


def test_the_handle_is_usable_as_lineage(tmp_path: Path, server: _Server) -> None:
    """``used=[raw]`` on a later registration records a reference to the pointer."""
    with _recording(_write_recipe(tmp_path, _URI_VERSION), tmp_path / "bundle"):
        build = setup()
        raw = build.use("raw")
        with build.bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular", name="derived", used=[raw])
        recorded = {r.name: r for r in build.bs.bundle.manifest.resources}

    assert recorded["derived"].used == ["raw"]
