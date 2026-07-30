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


def _said(exc: subprocess.CalledProcessError) -> str:
    """Return git's own stderr, so a diagnosis is never more confident than the evidence.

    A command fails for reasons other than the one being tested,
    such as dubious ownership under ``safe.directory`` or a held ``index.lock``,
    and the caller needs to see that rather than an authoritative guess.
    """
    detail = str(exc.stderr or "").strip()
    return f" git said: {detail}" if detail else ""


def derive_code_ref() -> str:
    """Return ``<remote-url>@<sha>[+dirty]`` for the current git checkout.

    Raises :class:`~bookshelf._core.errors.BookshelfError`
    naming which requirement is unmet:
    git is unavailable,
    this is not a repository,
    there is no ``origin`` remote,
    there is no commit to record,
    or there is no working tree to read state from.
    Each of those needs a different fix,
    so each is reported separately and carries git's own stderr.
    The caller may pass ``code_ref=`` explicitly instead.
    """
    # Every command shares one exec-layer diagnosis, because a git that cannot run
    # says nothing about which query was in flight.
    try:
        return _derive_code_ref()
    except OSError as exc:
        raise BookshelfError(
            f"Cannot derive code_ref: git could not be run ({exc}). Pass code_ref= explicitly."
        ) from exc


def _derive_code_ref() -> str:
    """Query git for the code ref, mapping each command's own failure to its cause."""
    try:
        _git("rev-parse", "--git-dir")
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: not inside a git repository. "
            f"Run from a clone, or pass code_ref= explicitly.{_said(exc)}"
        ) from exc

    try:
        remote = _git("remote", "get-url", "origin")
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: this repository has no 'origin' remote, "
            "so the code has no address to record. "
            f"Add one with 'git remote add origin <url>', or pass code_ref= explicitly.{_said(exc)}"
        ) from exc

    try:
        sha = _git("rev-parse", "HEAD")
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: this repository has no commits, "
            "so there is no revision to record. "
            f"Commit first, or pass code_ref= explicitly.{_said(exc)}"
        ) from exc

    try:
        dirty = _git("status", "--porcelain")
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: this repository has no working tree, "
            "so its state cannot be read. "
            f"Run from a normal clone, or pass code_ref= explicitly.{_said(exc)}"
        ) from exc

    ref = f"{remote}@{sha}"
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
