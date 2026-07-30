"""Tests for bookshelf._produce.provenance: git-derived activity provenance.

Record mode catches :class:`BookshelfError`,
so the contract these tests defend is that nothing else escapes ``derive_code_ref``.
"""

import subprocess
from pathlib import Path

import git
import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._produce.provenance import derive_code_ref


def _git(cwd: Path, *args: str) -> None:
    """Run one git command in ``cwd``, failing the test on a non-zero exit."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo_with_a_commit(path: Path) -> None:
    """Build a repository carrying an origin and one commit."""
    _git(path, "init")
    _git(path, "remote", "add", "origin", "https://example.com/thing")
    (path / "a.txt").write_text("a")
    _git(path, "add", "a.txt")
    _git(path, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "one")


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
    _repo_with_a_commit(tmp_path)
    monkeypatch.chdir(tmp_path)

    ref = derive_code_ref()

    assert ref.startswith("https://example.com/thing@")
    assert not ref.endswith("+dirty")


def test_an_uncommitted_change_marks_the_ref_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_a_commit(tmp_path)
    (tmp_path / "a.txt").write_text("changed")
    monkeypatch.chdir(tmp_path)

    assert derive_code_ref().endswith("+dirty")


def test_an_untracked_file_marks_the_ref_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unadded build output is a difference between the code and the recorded ref."""
    _repo_with_a_commit(tmp_path)
    (tmp_path / "new.txt").write_text("new")
    monkeypatch.chdir(tmp_path)

    assert derive_code_ref().endswith("+dirty")


def test_a_missing_git_binary_is_reported_as_unrunnable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo_with_a_commit(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")

    with pytest.raises(BookshelfError, match="git could not be run"):
        derive_code_ref()


def test_a_git_that_cannot_be_executed_is_reported_as_unrunnable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A present but non-executable git raises PermissionError, not a gitpython error."""
    _repo_with_a_commit(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "git").write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(fake_bin))

    with pytest.raises(BookshelfError, match="git could not be run"):
        derive_code_ref()


def test_an_unmapped_gitpython_error_still_becomes_a_bookshelf_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backstop exists so a gitpython error nobody anticipated cannot escape raw."""
    _repo_with_a_commit(tmp_path)
    monkeypatch.chdir(tmp_path)

    def _boom(*args: object, **kwargs: object) -> bool:
        raise git.GitError("something gitpython does that we did not map")

    monkeypatch.setattr(git.Repo, "is_dirty", _boom)

    with pytest.raises(BookshelfError, match="git could not be queried"):
        derive_code_ref()


def test_a_repository_git_refuses_to_read_is_reported_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gitpython reads refs and config without git's validation.

    This directory is a repository, so calling it missing or empty would be false.
    Only a real git command surfaces the config it rejects, which is why one runs first.
    """
    _git(tmp_path, "init")
    (tmp_path / ".git" / "config").write_text("[core]\n\trepositoryformatversion = 99\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(BookshelfError) as excinfo:
        derive_code_ref()

    message = str(excinfo.value)
    assert "refused to read" in message
    assert "found 99" in message, "git's own stderr carries the specifics"
    assert "no commits" not in message


def test_a_bare_repository_is_reported_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _repo_with_a_commit(source)

    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(bare)],
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(bare)

    with pytest.raises(BookshelfError, match="repository is bare"):
        derive_code_ref()


def test_a_subdirectory_resolves_the_containing_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Builds run from anywhere in the tree, so the walk up to the repository root matters."""
    _repo_with_a_commit(tmp_path)
    nested = tmp_path / "notebooks" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert derive_code_ref().startswith("https://example.com/thing@")
