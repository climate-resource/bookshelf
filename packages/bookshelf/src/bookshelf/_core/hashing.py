"""Shared content-hash helpers producing the canonical ``sha256:<hex>`` format.

Every digest in the SDK uses this one format,
covering output registration, notebook capture, bundle and lock hashing, and ``config_hash``,
so the formatting lives in exactly one place.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

_CHUNK_BYTES = 1 << 20


def sha256_hex(data: bytes) -> str:
    """Return the canonical ``sha256:<hex>`` digest for ``data``."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sha256_path(path: Path) -> str:
    """Return the canonical ``sha256:<hex>`` digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_json_bytes(obj: Any) -> bytes:
    """Return canonical JSON bytes for ``obj``.

    Uses ``sort_keys=True, separators=(",",":")``
    matching the backend convention so the same structure always serialises identically.
    This is the plain serialiser.
    It does not recursively sort list elements
    or drop ``None`` values (that pre-processing belongs to each call site).
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = ["canonical_json_bytes", "sha256_hex", "sha256_path"]
