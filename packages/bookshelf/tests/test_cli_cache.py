"""CLI tests for ``bookshelf cache`` over an isolated cache directory."""

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf.cache import ContentCache

runner = CliRunner()


def _hash_for(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "cli-cache"
    monkeypatch.setenv("BOOKSHELF_CACHE_DIR", str(target))
    return target


def test_path_prints_the_bare_directory(cache_dir: Path) -> None:
    result = runner.invoke(app, ["cache", "path"])
    assert result.exit_code == 0
    assert result.stdout == f"{cache_dir}\n"


def test_info_reports_entries_size_and_cap(cache_dir: Path) -> None:
    cache = ContentCache()
    cache.put(_hash_for(b"one"), b"one")
    cache.put(_hash_for(b"three"), b"three")
    result = runner.invoke(app, ["cache", "info", "--json"])
    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["entries"] == 2
    assert document["total_bytes"] == 8
    assert document["max_bytes"] > 0
    assert document["oldest"] is not None
    assert document["path"] == str(cache_dir)


def test_prune_evicts_oldest_entries_down_to_the_cap(cache_dir: Path) -> None:
    cache = ContentCache()
    cache.put(_hash_for(b"aaaa"), b"aaaa")
    cache.put(_hash_for(b"bbbb"), b"bbbb")
    result = runner.invoke(app, ["cache", "prune", "--max-bytes", "4", "--json"])
    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["bytes_freed"] == 4
    assert document["total_bytes"] == 4


def test_clear_requires_explicit_confirmation(cache_dir: Path) -> None:
    cache = ContentCache()
    cache.put(_hash_for(b"data"), b"data")
    result = runner.invoke(app, ["cache", "clear"])
    assert result.exit_code == 2
    assert "--yes" in result.stderr
    assert cache.summary().entries == 1

    result = runner.invoke(app, ["cache", "clear", "--yes", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["bytes_freed"] == 4
    assert cache.summary().entries == 0


def test_clear_leaves_foreign_files_alone(cache_dir: Path) -> None:
    """A user-supplied cache directory may hold files that are not entries."""
    cache = ContentCache()
    cache.put(_hash_for(b"data"), b"data")
    foreign = cache_dir / "notes.txt"
    foreign.write_text("keep me")
    result = runner.invoke(app, ["cache", "clear", "--yes", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["bytes_freed"] == 4
    assert foreign.read_text() == "keep me"
    assert cache.summary().entries == 0
