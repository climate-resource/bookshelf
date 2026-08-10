"""Shared content-hash helpers producing the canonical ``sha256:<hex>`` format.

Every digest in the SDK uses this one format,
covering output registration, notebook capture, bundle and lock hashing, and ``config_hash``,
so the formatting lives in exactly one place.
"""

import hashlib
import json
from typing import Any


def sha256_hex(data: bytes) -> str:
    """Return the canonical ``sha256:<hex>`` digest for ``data``."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def canonical_json_bytes(obj: Any) -> bytes:
    """Return canonical JSON bytes for ``obj``.

    Uses ``sort_keys=True, separators=(",",":")``
    matching the backend convention so the same structure always serialises identically.
    This is the plain serialiser.
    It does not recursively sort list elements
    or drop ``None`` values (that pre-processing belongs to each call site).
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = ["canonical_json_bytes", "sha256_hex"]
