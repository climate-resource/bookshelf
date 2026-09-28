"""Content integrity checks against a declared ``sha256:<hex>`` hash."""

import hmac
from pathlib import Path

from bookshelf._core.errors import BookshelfError
from bookshelf._core.hashing import sha256_path


class HashMismatchError(BookshelfError):
    """Downloaded bytes do not match the resource's declared SHA256."""


def verify_path(path: Path, content_hash: str) -> None:
    """Verify a file against its declared SHA256 without loading it into memory."""
    algorithm, separator, expected = content_hash.partition(":")
    if algorithm != "sha256" or not separator:
        raise HashMismatchError(f"unsupported resource hash {content_hash!r}")
    actual = sha256_path(path)
    if not hmac.compare_digest(actual, f"sha256:{expected.lower()}"):
        raise HashMismatchError(
            f"resource content hash mismatch: expected {content_hash}, got {actual}"
        )


__all__ = [
    "HashMismatchError",
    "verify_path",
]
