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
    """Return git's own stderr as supplemental detail, empty when git emitted none.

    A non-zero exit proves only that the query failed,
    never why it failed,
    so callers name the query and offer its usual cause as a possibility.
    The specifics come from here.
    """
    detail = str(exc.stderr or "").strip()
    return f" git said: {detail}" if detail else ""


def derive_code_ref() -> str:
    """Return ``<remote-url>@<sha>[+dirty]`` for the current git checkout.

    Raises :class:`~bookshelf._core.errors.BookshelfError`
    naming the query that failed:
    git could not be run,
    no repository could be identified,
    no ``origin`` remote could be read,
    ``HEAD`` could not be resolved,
    or the working tree state could not be read.
    Each query has a different usual cause and a different fix,
    so each is reported separately with its cause offered as a possibility.
    A repository whose config git refuses to read fails the first query
    without being the usual cause of that failure,
    which is why none of these is stated as established fact.
    Git's own stderr is appended whenever git ran and produced any.
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
    """Query git for the code ref, naming whichever query fails."""
    try:
        _git("rev-parse", "--git-dir")
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: git could not identify a repository here, "
            "usually because this is not a clone. "
            f"Run from one, or pass code_ref= explicitly.{_said(exc)}"
        ) from exc

    try:
        remote = _git("remote", "get-url", "origin")
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: git could not read an 'origin' remote, "
            "usually because none is set, so the code has no address to record. "
            f"Add one with 'git remote add origin <url>', or pass code_ref= explicitly.{_said(exc)}"
        ) from exc

    try:
        sha = _git("rev-parse", "HEAD")
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: git could not resolve HEAD, "
            "usually because the repository has no commits, "
            f"so there is no revision to record. Commit first, or pass code_ref= explicitly.{_said(exc)}"
        ) from exc

    try:
        dirty = _git("status", "--porcelain")
    except subprocess.CalledProcessError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: git could not read the working tree state, "
            "usually because the repository is bare. "
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
