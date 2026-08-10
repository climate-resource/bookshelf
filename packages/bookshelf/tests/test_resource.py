"""Tests for resolving declared resources: fetch, verify, cache and register."""

import hashlib
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._produce.books import DraftBook
from bookshelf.facade import Bookshelf
from bookshelf.publisher import resource as resource_module
from bookshelf.publisher.bundle import Bundle, BundleResource, BundleUsedRef
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
        pointer = _written_pointers(build.bs, bundle_path)[0]

    assert "doi" not in pointer.metadata
    assert pointer.external_uri == "data/raw.csv"


def test_the_handle_is_usable_as_lineage(tmp_path: Path, server: _Server) -> None:
    """``used=[raw]`` on a later registration records a reference to the pointer."""
    with _recording(_write_recipe(tmp_path, _URI_VERSION), tmp_path / "bundle"):
        build = setup()
        raw = build.use("raw")
        with build.bs.activity(kind="build", code_ref="test") as activity:
            derived = activity.register(b"data", type="tabular", used=[raw])
        recorded = {r.tracking_id: r for r in build.bs.bundle.manifest.resources}

    assert BundleUsedRef(tracking_id=raw.tracking_id) in recorded[derived.tracking_id].used
