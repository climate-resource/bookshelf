"""Git provenance and config-hash helpers for the activity surface."""

from __future__ import annotations

import subprocess
from typing import Any

from bookshelf._core.errors import BookshelfError
from bookshelf._core.hashing import canonical_json_bytes, sha256_hex


def _git(*args: str) -> str:
    """Return the stripped stdout of one git command."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def derive_code_ref() -> str:
    """Return ``<remote-url>@<sha>[+dirty]`` for the current git checkout.

    Raises :class:`~bookshelf._core.errors.BookshelfError`
    naming which requirement is unmet:
    git is unavailable,
    this is not a repository,
    there is no ``origin`` remote,
    or there is no commit to record.
    Each of those needs a different fix,
    so they are reported separately rather than as one ambiguous message.
    The caller may pass ``code_ref=`` explicitly instead.
    """
    try:
        _git("rev-parse", "--git-dir")
    except FileNotFoundError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: git is not installed or not on PATH. "
            "Pass code_ref= explicitly."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: not inside a git repository. "
            "Run from a clone, or pass code_ref= explicitly."
        ) from exc

    try:
        remote = _git("remote", "get-url", "origin")
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: this repository has no 'origin' remote, "
            "so the code has no address to record. "
            "Add one with 'git remote add origin <url>', or pass code_ref= explicitly."
        ) from exc

    try:
        sha = _git("rev-parse", "HEAD")
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: this repository has no commits, "
            "so there is no revision to record. "
            "Commit first, or pass code_ref= explicitly."
        ) from exc

    ref = f"{remote}@{sha}"
    if _git("status", "--porcelain"):
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
