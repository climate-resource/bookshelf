"""Git provenance and config-hash helpers for the activity surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bookshelf._core.errors import BookshelfError
from bookshelf._core.hashing import canonical_json_bytes, sha256_hex


def derive_code_ref() -> str:
    """Return ``<remote-url>@<sha>[+dirty]`` for the current git checkout.

    Raises :class:`~bookshelf._core.errors.BookshelfError` naming the unmet requirement,
    whether git cannot be run, this is not a usable repository, or it has no commits.
    The caller may pass ``code_ref=`` explicitly instead.
    """
    # gitpython raises at import time when the git binary is absent, and consuming a
    # book never needs git, so importing bookshelf must not depend on it.
    try:
        import git
    except ImportError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: git could not be run, "
            "because it is not installed or not on PATH. "
            "Pass code_ref= explicitly."
        ) from exc

    # Backstop, so nothing gitpython raises escapes as anything but a BookshelfError.
    try:
        return _derive_code_ref()
    except (git.GitError, OSError) as exc:
        raise BookshelfError(
            f"Cannot derive code_ref: git could not be queried ({exc}). Pass code_ref= explicitly."
        ) from exc


def _derive_code_ref() -> str:
    """Read the code ref from the repository containing the working directory."""
    import git

    try:
        repo = git.Repo(Path.cwd(), search_parent_directories=True)
    except git.NoSuchPathError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: the working directory no longer exists. "
            "Pass code_ref= explicitly."
        ) from exc
    except git.InvalidGitRepositoryError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: not inside a git repository. "
            "Run from a clone, or pass code_ref= explicitly."
        ) from exc

    # gitpython reads refs and config in pure Python, so a repository git itself rejects reads as empty.
    # Running a real git command first makes that failure surface as itself.
    try:
        dirty = repo.is_dirty(untracked_files=True)
    except (git.GitCommandNotFound, OSError) as exc:
        # A git that is absent, or present but not executable, lands here.
        raise BookshelfError(
            f"Cannot derive code_ref: git could not be run ({exc}). Pass code_ref= explicitly."
        ) from exc
    except git.GitCommandError as exc:
        detail = str(exc.stderr or "").strip()
        said = f" git said: {detail}" if detail else ""
        raise BookshelfError(
            "Cannot derive code_ref: git refused to read this repository. "
            f"Pass code_ref= explicitly.{said}"
        ) from exc

    if repo.bare:
        raise BookshelfError(
            "Cannot derive code_ref: this repository is bare, so it has no working tree "
            "whose state can be recorded. "
            "Run from a normal clone, or pass code_ref= explicitly."
        )
    if "origin" not in {remote.name for remote in repo.remotes}:
        raise BookshelfError(
            "Cannot derive code_ref: this repository has no 'origin' remote, "
            "so the code has no address to record. "
            "Add one with 'git remote add origin <url>', or pass code_ref= explicitly."
        )
    if not repo.head.is_valid():
        raise BookshelfError(
            "Cannot derive code_ref: this repository has no commits, "
            "so there is no revision to record. "
            "Commit first, or pass code_ref= explicitly."
        )

    ref = f"{repo.remotes.origin.url}@{repo.head.commit.hexsha}"
    if dirty:
        ref += "+dirty"
    return ref


def canonical_config_hash(config: dict[str, Any]) -> str:
    """Return the canonical ``sha256:<hex>`` digest for ``config``.

    Uses the platform's plain bundle-hash canonicalisation: ``sort_keys=True,
    separators=(",",":")`` via :func:`~bookshelf._core.hashing.canonical_json_bytes`.
    This is intentionally distinct from ``lock.py``'s recipe canonicaliser,
    which additionally recurse-sorts list elements and drops ``None`` values
    for the recipe-compile flow. The two agree on all flat configs.
    """
    return sha256_hex(canonical_json_bytes(config))


__all__ = ["canonical_config_hash", "derive_code_ref"]
