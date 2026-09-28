"""Content integrity helpers for consumed resources."""

import hashlib
import hmac
from pathlib import Path

from bookshelf._core.errors import BookshelfError

_HASH_CHUNK_SIZE = 1024 * 1024


class HashMismatchError(BookshelfError):
    """Downloaded bytes do not match the resource's declared SHA256."""


def verify_path(path: Path, content_hash: str) -> None:
    """Verify a file against its declared SHA256 without loading it into memory."""
    algorithm, separator, expected = content_hash.partition(":")
    if algorithm != "sha256" or not separator:
        raise HashMismatchError(f"unsupported resource hash {content_hash!r}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    actual = digest.hexdigest()
    if not hmac.compare_digest(actual, expected.lower()):
        raise HashMismatchError(
            f"resource content hash mismatch: expected {content_hash}, got sha256:{actual}"
        )


__all__ = [
    "HashMismatchError",
    "verify_path",
]
