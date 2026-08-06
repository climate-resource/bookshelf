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

    UPDATE_BUNDLE_GOLDENS=1 uv run --package bookshelf --locked --all-extras --python 3.13 pytest packages/bookshelf/tests/test_bundle_golden.py -r a -v
"""  # noqa: E501

import os
from pathlib import Path

import pytest

from bookshelf.publisher.bundle import (
    Bundle,
    BundleManifest,
    _dump_sorted_yaml,
    resource_filename,
)
from bookshelf.publisher.record import run_record

UPDATE_GOLDENS = os.environ.get("UPDATE_BUNDLE_GOLDENS") == "1"

REGENERATE = (
    "UPDATE_BUNDLE_GOLDENS=1 uv run --package bookshelf --locked --all-extras "
    "--python 3.13 pytest packages/bookshelf/tests/test_bundle_golden.py -r a -v"
)

GOLDEN_DIR = Path(__file__).parent / "golden"
BUILD_PATH = GOLDEN_DIR / "simple_build.py"
RECIPE_PATH = GOLDEN_DIR / "bookshelf.yaml"
SIMPLE_GOLDEN = GOLDEN_DIR / "simple"

# The two documents ``run_record`` attaches to every recorded book.
_DOCUMENT_KINDS = frozenset({"notebook", "notebook-html"})


def _record_golden_bundle(tmp_path: Path) -> Bundle:
    """Record the fixture build into ``tmp_path`` and read the bundle back."""
    bundle_path = tmp_path / "bundle"
    run_record(
        build_path=BUILD_PATH,
        recipe_path=RECIPE_PATH,
        bundle_path=bundle_path,
        cwd=GOLDEN_DIR,
    )
    return Bundle.read_validated(bundle_path)


def _without_executed_documents(manifest: BundleManifest) -> BundleManifest:
    """Return the manifest with the executed-document resources and entries dropped.

    The documents are identified by the ``kind`` their recorder stamps on them,
    so the filter names exactly two records rather than guessing at their names.
    """
    filtered = manifest.model_copy(deep=True)
    excluded = {
        resource.tracking_id
        for resource in filtered.resources
        if resource.metadata.get("kind") in _DOCUMENT_KINDS
    }
    filtered.resources = [
        resource for resource in filtered.resources if resource.tracking_id not in excluded
    ]
    if filtered.book is not None:
        filtered.book.entries = [
            entry for entry in filtered.book.entries if entry.tracking_id not in excluded
        ]
    return filtered


def _resource_filenames(manifest: BundleManifest) -> bytes:
    """Return the sorted byte-file names of every managed resource, one per line."""
    names = sorted(
        resource_filename(resource.hash, resource.type)
        for resource in manifest.resources
        if resource.kind == "managed"
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

    actual = _dump_sorted_yaml(_without_executed_documents(bundle.manifest))

    _assert_matches_golden(actual, SIMPLE_GOLDEN / "manifest.lock")


def test_the_recorded_resource_filenames_match_the_golden(tmp_path: Path) -> None:
    bundle = _record_golden_bundle(tmp_path)

    actual = _resource_filenames(_without_executed_documents(bundle.manifest))

    _assert_matches_golden(actual, SIMPLE_GOLDEN / "resources.txt")


def test_the_executed_notebook_and_its_html_are_attached_to_the_book(tmp_path: Path) -> None:
    """The documents are excluded from the golden, so their absence needs its own assertion."""
    bundle = _record_golden_bundle(tmp_path)
    excluded = {
        resource.tracking_id
        for resource in bundle.manifest.resources
        if resource.metadata.get("kind") in _DOCUMENT_KINDS
    }

    names = sorted(
        entry.name_in_book
        for entry in bundle.require_framing().entries
        if entry.tracking_id in excluded
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

    with pytest.raises(AssertionError, match="UPDATE_BUNDLE_GOLDENS=1"):
        _assert_matches_golden(b"fresh bytes\n", golden, update=False)
