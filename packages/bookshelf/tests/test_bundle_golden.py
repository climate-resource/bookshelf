"""Golden regression over the bytes a recorded bundle writes.

Every other test in this suite asserts on parsed objects,
so a refactor of the recorder can rename a field, drop a key, reorder a list
or change how a resource filename is derived, and the suite still passes.
This module compares the bytes instead,
which turns each of those into a visible diff in the pull request that caused it.

The two executed-document resources are excluded from the golden.
Their bytes come from nbconvert, whose HTML output is not stable across template versions,
so including them would tie the golden to a rendering dependency.
They are asserted separately, by name, so their disappearance is still caught.

An intended format change is regenerated rather than hand-edited::

    make test-golden-update
"""

import os
from pathlib import Path

import pytest

from bookshelf.publisher.bundle import (
    Bundle,
    BundleManifest,
    BundleResource,
    resource_filename,
)
from bookshelf.publisher.record import DOCUMENT_KINDS, run_record

UPDATE_GOLDENS = os.environ.get("UPDATE_BUNDLE_GOLDENS") == "1"

REGENERATE = "make test-golden-update"

GOLDEN_DIR = Path(__file__).parent / "golden"
BUILD_PATH = GOLDEN_DIR / "simple_build.py"
RECIPE_PATH = GOLDEN_DIR / "bookshelf.yaml"
SIMPLE_GOLDEN = GOLDEN_DIR / "simple"
GOLDEN_VERSION = "v1.0.0"


def _record_golden_bundle(tmp_path: Path) -> Bundle:
    """Record the fixture build into ``tmp_path`` and read the bundle back."""
    bundle_path = tmp_path / "bundle"
    run_record(
        build_path=BUILD_PATH,
        recipe_path=RECIPE_PATH,
        bundle_path=bundle_path,
        version=GOLDEN_VERSION,
        cwd=GOLDEN_DIR,
    )
    return Bundle.read_validated(bundle_path)


def _documents(manifest: BundleManifest) -> list[BundleResource]:
    """Return the executed-document resources, identified by the ``kind`` their recorder stamps."""
    return [
        resource
        for resource in manifest.resources
        if resource.metadata.get("kind") in DOCUMENT_KINDS
    ]


def _without_executed_documents(manifest: BundleManifest) -> BundleManifest:
    """Return the manifest with the executed-document resources and entries dropped."""
    filtered = manifest.model_copy(deep=True)
    excluded = {resource.name for resource in _documents(filtered)}
    filtered.resources = [
        resource for resource in filtered.resources if resource.name not in excluded
    ]
    if filtered.book is not None:
        filtered.book.entries = [
            entry for entry in filtered.book.entries if entry.name not in excluded
        ]
    return filtered


def _resource_filenames(bundle: Bundle) -> bytes:
    """Return the sorted on-disk byte-file names under ``resources/``, one per line.

    The names come from the directory listing rather than from the manifest,
    so a recorder that wrote a byte file under a diverging name would fail the golden.
    The two executed documents are subtracted, matching the manifest golden.
    """
    documents = {
        resource_filename(resource.hash, resource.type) for resource in _documents(bundle.manifest)
    }
    names = sorted(
        path.name for path in bundle.resources_dir.iterdir() if path.name not in documents
    )
    return ("\n".join(names) + "\n").encode("utf-8")


def _assert_matches_golden(actual: bytes, golden: Path, *, update: bool = UPDATE_GOLDENS) -> None:
    """Compare bytes against a golden file, or rewrite it under the update flag."""
    if update:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_bytes(actual)
        return
    assert golden.is_file(), f"golden {golden} does not exist. Regenerate it with:\n{REGENERATE}"
    expected = golden.read_bytes()
    assert actual == expected, (
        f"{golden.name} does not match the recorded bundle.\n"
        f"If the format change is intended, regenerate the goldens with:\n{REGENERATE}"
    )


def test_the_recorded_manifest_matches_the_golden_bytes(tmp_path: Path) -> None:
    bundle = _record_golden_bundle(tmp_path)

    # Written through Bundle.write, so the golden covers the real serialisation path.
    filtered = Bundle(tmp_path / "filtered", manifest=_without_executed_documents(bundle.manifest))
    filtered.write()

    _assert_matches_golden(filtered.manifest_path.read_bytes(), SIMPLE_GOLDEN / "manifest.lock")


def test_the_recorded_resource_filenames_match_the_golden(tmp_path: Path) -> None:
    bundle = _record_golden_bundle(tmp_path)

    actual = _resource_filenames(bundle)

    _assert_matches_golden(actual, SIMPLE_GOLDEN / "resources.txt")


def test_the_executed_notebook_and_its_html_are_attached_to_the_book(tmp_path: Path) -> None:
    """The documents are excluded from the golden, so their absence needs its own assertion."""
    bundle = _record_golden_bundle(tmp_path)
    excluded = {resource.name for resource in _documents(bundle.manifest)}

    names = sorted(
        entry.name for entry in bundle.require_framing().entries if entry.name in excluded
    )

    assert names == ["simple_build.html", "simple_build.ipynb"]


def test_the_update_flag_writes_the_golden_it_was_asked_for(tmp_path: Path) -> None:
    """The update path is exercised against a throwaway target, not the checked-in goldens."""
    golden = tmp_path / "goldens" / "manifest.lock"

    _assert_matches_golden(b"fresh bytes\n", golden, update=True)

    assert golden.read_bytes() == b"fresh bytes\n"


def test_a_mismatch_names_the_regeneration_command(tmp_path: Path) -> None:
    """A failing golden must say how to accept an intended change."""
    golden = tmp_path / "manifest.lock"
    golden.write_bytes(b"stale bytes\n")

    with pytest.raises(AssertionError, match="make test-golden-update"):
        _assert_matches_golden(b"fresh bytes\n", golden, update=False)
