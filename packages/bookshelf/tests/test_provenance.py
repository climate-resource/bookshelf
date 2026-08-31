"""Tests for bookshelf._produce.provenance: git-derived activity provenance.

Record mode catches :class:`BookshelfError`,
so the contract these tests defend is that nothing else escapes ``derive_code_ref``.
"""

import subprocess
from pathlib import Path

import git
import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._produce.provenance import _sanitise_remote_url, derive_code_ref, source_url

# A globally configured core.hooksPath applies to a throwaway repository too,
# so hooks are switched off to keep these independent of the machine they run on.
_NO_HOOKS = ("-c", "core.hooksPath=/dev/null")


def _git(cwd: Path, *args: str) -> None:
    """Run one git command in ``cwd``, failing the test on a non-zero exit."""
    subprocess.run(["git", *_NO_HOOKS, *args], cwd=cwd, check=True, capture_output=True)


def _repo_with_a_commit(path: Path, origin: str = "https://example.com/thing") -> None:
    """Build a repository carrying an origin and one commit."""
    _git(path, "init")
    _git(path, "remote", "add", "origin", origin)
    (path / "a.txt").write_text("a")
    _git(path, "add", "a.txt")
    _git(path, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "one")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:tok@example.com/org/repo.git", "https://example.com/org/repo.git"),
        ("https://tok@example.com/org/repo.git", "https://example.com/org/repo.git"),
        ("https://example.com/org/repo.git", "https://example.com/org/repo.git"),
        (
            "https://user:tok@example.com:8443/org/repo.git",
            "https://example.com:8443/org/repo.git",
        ),
        ("ssh://git@example.com/org/repo.git", "ssh://example.com/org/repo.git"),
        ("https://user:tok@[2001:db8::1]:443/x.git", "https://[2001:db8::1]:443/x.git"),
        ("https://user:tok@[2001:db8::1]/x.git", "https://[2001:db8::1]/x.git"),
        ("git@github.com:org/repo.git", "git@github.com:org/repo.git"),
        ("/srv/local/repo.git", "/srv/local/repo.git"),
    ],
)
def test_the_sanitiser_keeps_the_address_and_drops_the_userinfo(url: str, expected: str) -> None:
    assert _sanitise_remote_url(url) == expected


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


def test_a_credential_in_the_origin_never_reaches_the_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI systems set origin to a token-bearing URL, and provenance is published and immutable."""
    _repo_with_a_commit(tmp_path, origin="https://user:tok@example.com/thing")
    monkeypatch.chdir(tmp_path)

    ref = derive_code_ref()

    assert ref.startswith("https://example.com/thing@")
    assert "tok" not in ref
    assert "user" not in ref


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


def test_a_silent_git_failure_leaves_no_dangling_quote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git does not always write to stderr, and the message must still read cleanly."""
    _repo_with_a_commit(tmp_path)
    monkeypatch.chdir(tmp_path)

    def _fail_quietly(*args: object, **kwargs: object) -> bool:
        raise git.GitCommandError(["git", "status"], 1, stderr="")

    monkeypatch.setattr(git.Repo, "is_dirty", _fail_quietly)

    with pytest.raises(BookshelfError) as excinfo:
        derive_code_ref()

    message = str(excinfo.value)
    assert "refused to read" in message
    assert "git said" not in message
    assert message.endswith("Pass code_ref= explicitly.")


def test_a_bare_repository_is_reported_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _repo_with_a_commit(source)

    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", *_NO_HOOKS, "clone", "--bare", str(source), str(bare)],
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


_SHA = "b9aa2996d890d16691d9978ec4f1772f5e51b0f1"


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        (
            "git@github.com:climate-resource/feedstock.git",
            f"https://github.com/climate-resource/feedstock/blob/{_SHA}/inputs/raw.csv",
        ),
        (
            "https://github.com/climate-resource/feedstock.git",
            f"https://github.com/climate-resource/feedstock/blob/{_SHA}/inputs/raw.csv",
        ),
        (
            "https://github.com/climate-resource/feedstock",
            f"https://github.com/climate-resource/feedstock/blob/{_SHA}/inputs/raw.csv",
        ),
        (
            "ssh://git@gitlab.com/group/proj.git",
            f"https://gitlab.com/group/proj/-/blob/{_SHA}/inputs/raw.csv",
        ),
    ],
)
def test_a_checked_in_file_links_to_the_commit_it_was_read_at(remote: str, expected: str) -> None:
    """Every remote form a clone may carry resolves to the same web address."""
    assert source_url(f"{remote}@{_SHA}", "inputs/raw.csv") == expected


@pytest.mark.parametrize(
    "code_ref",
    [
        # A dirty tree means the revision does not name the bytes that were read.
        f"git@github.com:org/repo.git@{_SHA}+dirty",
        # A forge whose URL layout this does not know.
        f"git@git.example.com:org/repo.git@{_SHA}",
        "https://github.com/org/repo.git@not-a-sha",
        "nonsense",
    ],
)
def test_no_honest_link_is_no_link(code_ref: str) -> None:
    """A link is a convenience, so anything it cannot state truthfully it omits."""
    assert source_url(code_ref, "inputs/raw.csv") is None


def test_a_path_with_a_space_is_escaped() -> None:
    assert source_url(f"git@github.com:o/r.git@{_SHA}", "inputs/two words.csv").endswith(
        "/inputs/two%20words.csv"
    )
