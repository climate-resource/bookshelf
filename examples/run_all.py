"""Record every example, validate it, and compare it against its golden.

Each example directory is a miniature feedstock.
This runner is what makes the set a regression gate rather than a pile of sample files:
it records each book the recipe declares, asserts the bundle is valid, and compares the
manifest bytes and the resource filenames against the ``expected/`` golden checked in beside it.

Run it with no arguments to run every offline example::

    python examples/run_all.py

An intended format change is accepted by regenerating rather than by hand-editing::

    UPDATE_BUNDLE_GOLDENS=1 python examples/run_all.py

That is the same switch ``make test-golden-update`` uses for the bundle golden, because one
repository gets one way to refresh a golden.
``--update-golden`` is an alias for it and nothing more.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from uuid import UUID

from bookshelf.publisher.bundle import (
    Bundle,
    BundleManifest,
    InvalidBundleError,
    resource_filename,
)
from bookshelf.publisher.recipe import load_record_recipe
from bookshelf.publisher.record import DOCUMENT_KINDS, run_record

EXAMPLES_DIR = Path(__file__).parent
RECIPE_NAME = "bookshelf.yaml"
SCRIPT_NAME = "record.py"
GOLDEN_DIRNAME = "expected"
MANIFEST_GOLDEN = "manifest.lock"
RESOURCES_GOLDEN = "resources.txt"

REGENERATE = "UPDATE_BUNDLE_GOLDENS=1 python examples/run_all.py"

# What varies by machine, by working tree, or by commit, and is pinned before comparing.
# Without this every developer's goldens would differ, and every commit would move them.
PINNED_CODE_REF = "https://example.invalid/examples@0000000000000000000000000000000000000000"
PINNED_RUNNER = "examples"
PINNED_ACTIVITY_ID = UUID("00000000-0000-7000-8000-000000000000")


class Status(StrEnum):
    """What happened to one book of one example."""

    OK = "OK"
    UPDATED = "UPDATED"
    SKIP = "SKIP"
    FAIL = "FAIL"

    @property
    def passed(self) -> bool:
        """Whether this outcome counts as the example having run and been accepted."""
        return self in {Status.OK, Status.UPDATED}


@dataclass(frozen=True, slots=True)
class Outcome:
    """What happened to one book of one example."""

    example: str
    version: str
    status: Status
    detail: str = ""


def needs_network(recipe_path: Path) -> bool:
    """Whether any book of this recipe declares a resource that must be fetched.

    A ``uri:`` resource is fetched and a ``path:`` resource is read from beside the recipe,
    so the recipe already says which examples reach the network
    and no separate declaration has to be kept in step with it.
    """
    recipe = load_record_recipe(recipe_path)
    return any(resource.uri is not None for book in recipe.books for resource in book.resources.values())


def documents(manifest: BundleManifest) -> set[str]:
    """Return the names of the executed-document resources, found by the kind their recorder stamps.

    Their bytes come from nbconvert, whose HTML is not stable across template versions,
    so a golden over them would pin a rendering dependency rather than the bundle format.
    """
    return {
        resource.name for resource in manifest.resources if resource.metadata.get("kind") in DOCUMENT_KINDS
    }


def normalised(manifest: BundleManifest, excluded: set[str]) -> BundleManifest:
    """Return the manifest with the machine-varying values pinned and the excluded resources dropped."""
    pinned = manifest.model_copy(deep=True)
    if pinned.activity is not None:
        pinned.activity.code_ref = PINNED_CODE_REF
        pinned.activity.runner = PINNED_RUNNER
        pinned.activity.activity_id = PINNED_ACTIVITY_ID
    pinned.resources = [resource for resource in pinned.resources if resource.name not in excluded]
    for resource in pinned.resources:
        # A checked-in input links to the commit it was read at, and a dirty tree records no
        # link at all, so whether one is here tracks the checkout rather than the bundle format.
        resource.metadata.pop("source_url", None)
    if pinned.book is not None:
        pinned.book.entries = [entry for entry in pinned.book.entries if entry.name not in excluded]
        # The fingerprint is the activity's, and the activity's is pinned above.
        if pinned.book.processing:
            pinned.book.processing = [
                (PINNED_CODE_REF, config_hash) for _, config_hash in pinned.book.processing
            ]
    return pinned


def _resource_filenames(bundle: Bundle, excluded_names: set[str]) -> bytes:
    """Return the sorted on-disk byte-file names under ``resources/``, one per line.

    Read from the directory rather than from the manifest,
    so a recorder that wrote a byte file under a diverging name fails the golden.
    """
    excluded = {
        resource_filename(resource.hash, resource.type)
        for resource in bundle.manifest.resources
        if resource.name in excluded_names
    }
    if not bundle.resources_dir.is_dir():
        return b"\n"
    names = sorted(path.name for path in bundle.resources_dir.iterdir() if path.name not in excluded)
    return ("\n".join(names) + "\n").encode("utf-8")


def _compare(actual: bytes, golden: Path, *, update: bool) -> str | None:
    """Compare bytes against a golden file, or rewrite it. Returns a failure message or ``None``."""
    if update:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_bytes(actual)
        return None
    if not golden.is_file():
        return f"golden {golden.name} does not exist. Regenerate it with:\n  {REGENERATE}"
    if golden.read_bytes() != actual:
        return f"{golden.name} does not match. If the change is intended, run:\n  {REGENERATE}"
    return None


def _record_script(directory: Path, bundle_path: Path) -> None:
    """Run a script example the way a user would, so it owns its own command line."""
    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(directory / SCRIPT_NAME), "--bundle", str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=directory,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())


def run_example(directory: Path, *, update: bool) -> list[Outcome]:
    """Record, validate and compare every book one example declares.

    A recipe example is recorded once per declared version.
    A script example is recorded once, and its version is read back off the bundle,
    because the script is the only place that states one.
    """
    recipe_path = directory / RECIPE_NAME
    runs: list[tuple[str, Callable[..., object]]]
    if recipe_path.is_file():
        recipe = load_record_recipe(recipe_path)
        runs = [
            (
                book.version,
                partial(
                    run_record, build_path=None, recipe_path=recipe_path, version=book.version, cwd=directory
                ),
            )
            for book in recipe.books
        ]
    else:
        runs = [("-", partial(_record_script, directory))]

    outcomes: list[Outcome] = []
    for version, record in runs:
        with tempfile.TemporaryDirectory(prefix="bookshelf-example-") as scratch:
            bundle_path = Path(scratch) / "bundle"
            try:
                record(bundle_path=bundle_path)
                outcomes.append(_compare_bundle(directory, bundle_path, Path(scratch), update=update))
            except Exception as error:
                outcomes.append(
                    Outcome(directory.name, version, Status.FAIL, f"{type(error).__name__}: {error}")
                )
    return outcomes


def _compare_bundle(directory: Path, bundle_path: Path, scratch: Path, *, update: bool) -> Outcome:
    """Validate a recorded bundle and compare it against the golden for its version."""
    bundle = Bundle.read(bundle_path)
    bundle.validate()
    # A bookless bundle is a catalogue run, and framing is what a book adds.
    if bundle.manifest.book is not None:
        bundle.require_framing()
    version = bundle.manifest.book.version if bundle.manifest.book is not None else "-"

    golden_dir = directory / GOLDEN_DIRNAME / version
    excluded = documents(bundle.manifest)
    comparable = Bundle(scratch / "normalised", manifest=normalised(bundle.manifest, excluded))
    comparable.write()

    failures = [
        message
        for message in (
            _compare(comparable.manifest_path.read_bytes(), golden_dir / MANIFEST_GOLDEN, update=update),
            _compare(_resource_filenames(bundle, excluded), golden_dir / RESOURCES_GOLDEN, update=update),
        )
        if message is not None
    ]
    if failures:
        return Outcome(directory.name, version, Status.FAIL, "\n".join(failures))
    return Outcome(directory.name, version, Status.UPDATED if update else Status.OK)


def discover() -> list[Path]:
    """Every example directory, in name order.

    An example is either a recipe the recorder drives or a script that records for itself,
    so both entrypoints are looked for.
    """
    found = {path.parent for path in EXAMPLES_DIR.glob(f"*/{RECIPE_NAME}")}
    found |= {path.parent for path in EXAMPLES_DIR.glob(f"*/{SCRIPT_NAME}")}
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    """Run the selected examples and report, returning the process exit status."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--network",
        action="store_true",
        help="also run the examples that fetch a declared uri. They are skipped by default.",
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="alias for UPDATE_BUNDLE_GOLDENS=1, the one golden refresh switch in this repository.",
    )
    parser.add_argument(
        "--example",
        action="append",
        default=None,
        help="run only the named example. Repeatable.",
    )
    args = parser.parse_args(argv)
    update = args.update_golden or os.environ.get("UPDATE_BUNDLE_GOLDENS") == "1"

    outcomes: list[Outcome] = []
    for directory in discover():
        if args.example is not None and directory.name not in args.example:
            continue
        recipe_path = directory / RECIPE_NAME
        try:
            skip = not args.network and recipe_path.is_file() and needs_network(recipe_path)
        except (InvalidBundleError, ValueError) as error:
            outcomes.append(Outcome(directory.name, "-", Status.FAIL, f"unreadable recipe: {error}"))
            continue
        if skip:
            outcomes.append(Outcome(directory.name, "-", Status.SKIP, "needs the network"))
            continue
        outcomes.extend(run_example(directory, update=update))

    width = max((len(f"{o.example}@{o.version}") for o in outcomes), default=1)
    for outcome in outcomes:
        print(f"{outcome.example}@{outcome.version}".ljust(width) + f"  {outcome.status}")
        if outcome.detail:
            for line in outcome.detail.splitlines():
                print(f"    {line}")

    failed = [outcome for outcome in outcomes if outcome.status is Status.FAIL]
    print(
        f"\n{len(outcomes)} recorded, "
        f"{sum(o.status.passed for o in outcomes)} passed, "
        f"{sum(o.status is Status.SKIP for o in outcomes)} skipped, "
        f"{len(failed)} failed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
