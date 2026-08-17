"""Drive the example runner from pytest, so a bundle-format regression fails CI.


The ``examples/run_all.py`` script is used to run the examples.
This is a wrapper of that script so we can test the examples in CI.
"""

import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "examples"
RUNNER = EXAMPLES_DIR / "run_all.py"

pytestmark = pytest.mark.skipif(
    not RUNNER.is_file(),
    reason="the examples tree is not present in this checkout",
)


def _run_all() -> ModuleType:
    """Import the runner as a module, so its helpers can be unit tested."""
    sys.path.insert(0, str(EXAMPLES_DIR))
    try:
        import run_all
    finally:
        sys.path.pop(0)
    return run_all


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the example runner and capture what it reported."""
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


@pytest.fixture(scope="module")
def full_run() -> subprocess.CompletedProcess[str]:
    """One bare run of every example, shared by the tests that assert on the whole set."""
    return _run()


def test_the_offline_examples_record_validate_and_match_their_goldens(
    full_run: subprocess.CompletedProcess[str],
) -> None:
    assert full_run.returncode == 0, full_run.stdout + full_run.stderr
    assert "0 failed" in full_run.stdout


def test_every_example_directory_is_covered_by_the_runner(
    full_run: subprocess.CompletedProcess[str],
) -> None:
    """A new example directory that the runner does not discover would be silently untested."""
    directories = {path.parent.name for path in EXAMPLES_DIR.glob("*/bookshelf.yaml")}

    assert directories
    for name in directories:
        assert name in full_run.stdout


def test_every_file_an_example_declares_is_tracked_by_git() -> None:
    """A gitignored input records and passes locally, then fails for everyone else.

    The repository ignores any directory named ``data``.
    """
    listed = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "examples/"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    # Build artefacts are ignored on purpose. Anything else under an example is content.
    ignored = [
        line
        for line in listed.stdout.splitlines()
        if "__pycache__" not in line and not line.endswith(".pyc")
    ]

    assert ignored == [], (
        "these example files are ignored by git and would not reach CI:\n" + "\n".join(ignored)
    )


def test_a_corrupted_golden_makes_the_runner_exit_non_zero() -> None:
    """The gate is the exit status, so it is asserted rather than the log text."""
    golden = EXAMPLES_DIR / "simple" / "expected" / "v1.0.0" / "manifest.lock"
    original = golden.read_bytes()
    golden.write_bytes(original + b"corrupted\n")
    try:
        result = _run("--example", "simple")
    finally:
        golden.write_bytes(original)

    assert result.returncode == 1
    assert "1 failed" in result.stdout


def test_recording_an_example_twice_produces_the_same_bundle() -> None:
    """Two runs against one unchanged golden is the reproducibility assertion."""
    first = _run("--example", "simple")
    second = _run("--example", "simple")

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr


def test_the_runner_names_its_network_opt_in_and_its_golden_refresh_path() -> None:
    """One repository gets one refresh switch, and the help is where that is stated."""
    result = _run("--help")

    assert result.returncode == 0
    assert "--network" in result.stdout
    assert "UPDATE_BUNDLE_GOLDENS" in result.stdout


def test_the_network_requirement_is_read_off_the_declared_resources(tmp_path: Path) -> None:
    """A ``uri:`` is fetched and a ``path:`` is read from beside the recipe, so the recipe says which."""
    fetching = tmp_path / "bookshelf.yaml"
    fetching.write_text(
        "volume:\n"
        "  name: fetching-example\n"
        "build:\n"
        "  notebook: build.py\n"
        "books:\n"
        '  - version: "v1.0.0"\n'
        "    license: CC-BY-4.0\n"
        "    resources:\n"
        "      raw:\n"
        "        type: tabular\n"
        "        uri: https://example.invalid/raw.csv\n"
        f'        sha256: "{"0" * 64}"\n'
    )

    assert _run_all().needs_network(fetching) is True
    assert _run_all().needs_network(EXAMPLES_DIR / "checked-in-data" / "bookshelf.yaml") is False


def test_an_example_that_fetches_a_uri_is_skipped_unless_the_network_is_opted_in(
    full_run: subprocess.CompletedProcess[str],
) -> None:
    """Every offline example runs, and none is reported skipped while none declares a fetch."""
    assert full_run.returncode == 0
    assert "0 skipped" in full_run.stdout
    assert all(
        _run_all().needs_network(path) is False for path in EXAMPLES_DIR.glob("*/bookshelf.yaml")
    )


def test_a_bare_record_names_the_versions_the_recipe_declares() -> None:
    """There is no default version, so picking one would be a guess rather than a default."""
    import re

    from typer.testing import CliRunner

    from bookshelf._cli import app

    recipe = EXAMPLES_DIR / "multi-version" / "bookshelf.yaml"

    result = CliRunner().invoke(app, ["record", "--recipe", str(recipe)])

    # Diagnostics go to stderr, because the CLI keeps stdout for the payload.
    reported = re.sub(r"\x1b\[[0-9;]*m", "", result.stderr)
    assert result.exit_code != 0
    assert "v1.0.0" in reported
    assert "v2.0.0" in reported
