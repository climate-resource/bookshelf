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
    # The ceiling stops git walking up, so the result does not depend on where TMPDIR sits.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BookshelfError, match="could not identify a repository"):
        derive_code_ref()


def test_a_missing_origin_remote_names_the_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BookshelfError, match="could not read an 'origin' remote"):
        derive_code_ref()


def test_a_repository_with_no_commits_names_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "remote", "add", "origin", "https://example.com/thing")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BookshelfError, match="could not resolve HEAD"):
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


def test_an_unrunnable_git_is_reported_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")

    with pytest.raises(BookshelfError, match="git could not be run"):
        derive_code_ref()


def test_a_git_that_cannot_be_executed_stays_on_the_bookshelf_error_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A present but non-executable git raises PermissionError, not FileNotFoundError."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "git").write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(fake_bin))

    with pytest.raises(BookshelfError, match="git could not be run"):
        derive_code_ref()


def test_an_exec_failure_after_the_first_command_is_still_a_bookshelf_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the first command used to be guarded, so later exec failures escaped raw."""
    _git(tmp_path, "init")
    _git(tmp_path, "remote", "add", "origin", "https://example.com/thing")
    monkeypatch.chdir(tmp_path)

    real_run = subprocess.run
    calls = {"n": 0}

    def _fail_after_the_first(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError(24, "Too many open files")
        return real_run(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", _fail_after_the_first)

    with pytest.raises(BookshelfError, match="git could not be run"):
        derive_code_ref()


def test_a_failure_carries_gits_own_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The diagnosis must not sound more certain than the evidence behind it."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BookshelfError, match="git said:"):
        derive_code_ref()


def test_a_repository_git_refuses_to_read_is_not_called_a_missing_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero exit proves the query failed, not that the usual cause applies.

    This directory is a repository, so any message asserting otherwise is false.
    """
    _git(tmp_path, "init")
    (tmp_path / ".git" / "config").write_text("[core]\n\trepositoryformatversion = 99\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BookshelfError) as excinfo:
        derive_code_ref()

    message = str(excinfo.value)
    assert "usually because" in message
    assert "git said:" in message
    assert "found 99" in message


def test_a_repository_with_no_working_tree_is_reported_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare repository answers every other query, so only `git status` catches it."""
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    (source / "a.txt").write_text("a")
    _git(source, "add", "a.txt")
    _git(source, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "one")

    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(bare)],
        check=True,
        capture_output=True,
    )
    # The bare clone already carries an origin pointing at its source.
    monkeypatch.chdir(bare)

    with pytest.raises(BookshelfError, match="could not read the working tree state"):
        derive_code_ref()
