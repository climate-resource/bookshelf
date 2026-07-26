"""Git provenance and config-hash helpers for the activity surface."""

from __future__ import annotations

import subprocess
from typing import Any

from bookshelf._core.errors import BookshelfError
from bookshelf._core.hashing import canonical_json_bytes, sha256_hex


def derive_code_ref() -> str:
    """Return ``<remote-url>@<sha>[+dirty]`` for the current git checkout.

    Raises :class:`~bookshelf._core.errors.BookshelfError`
    when the working directory is not inside a git repository
    or when git is unavailable.
    The caller must pass ``code_ref=`` explicitly in that case.
    """
    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = (
            subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            != ""
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise BookshelfError(
            "Cannot derive code_ref: not inside a git repository "
            "(or git is not available). Pass code_ref= explicitly."
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
