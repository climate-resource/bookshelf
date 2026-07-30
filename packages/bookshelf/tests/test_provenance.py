"""Tests for bookshelf._produce.provenance: git-derived activity provenance."""

import subprocess
from pathlib import Path

import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._produce.provenance import derive_code_ref


def _git(cwd: Path, *args: str) -> None:
    """Run one git command in ``cwd``, failing the test on a non-zero exit."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_outside_a_repository_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BookshelfError, match="not inside a git repository"):
        derive_code_ref()


def test_a_missing_origin_remote_names_the_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BookshelfError, match="no 'origin' remote"):
        derive_code_ref()


def test_a_repository_with_no_commits_names_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "remote", "add", "origin", "https://example.com/thing")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BookshelfError, match="no commits"):
        derive_code_ref()


def test_a_clean_checkout_derives_remote_and_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "remote", "add", "origin", "https://example.com/thing")
    (tmp_path / "a.txt").write_text("a")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "one")
    monkeypatch.chdir(tmp_path)

    ref = derive_code_ref()

    assert ref.startswith("https://example.com/thing@")
    assert not ref.endswith("+dirty")


def test_an_uncommitted_change_marks_the_ref_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "remote", "add", "origin", "https://example.com/thing")
    (tmp_path / "a.txt").write_text("a")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "one")
    (tmp_path / "a.txt").write_text("changed")
    monkeypatch.chdir(tmp_path)

    assert derive_code_ref().endswith("+dirty")


def test_a_missing_git_binary_is_reported_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def _no_git(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", _no_git)

    with pytest.raises(BookshelfError, match="git is not installed"):
        derive_code_ref()
