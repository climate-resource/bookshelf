"""Content integrity helpers for consumed resources."""

import hashlib
import hmac
from pathlib import Path

from bookshelf._core.errors import BookshelfError
from bookshelf.cache import ContentCache

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


def cached_if_verified(cache: ContentCache, content_hash: str) -> Path | None:
    """Return the cached path when the cached bytes still match the declared hash.

    A cache hit is always re-verified, and content that fails verification is discarded
    so the caller downloads it again.
    """
    cached = cache.get(content_hash)
    if cached is None:
        return None
    try:
        verify_path(cached, content_hash)
    except (FileNotFoundError, HashMismatchError):
        cache.discard(content_hash)
        return None
    return cached


def require_cached(cache: ContentCache, content_hash: str) -> Path:
    """Return the path of content that has just been staged and verified."""
    cached = cache.get(content_hash)
    if cached is None:  # pragma: no cover
        raise BookshelfError("verified resource disappeared from the content cache")
    return cached


__all__ = [
    "HashMismatchError",
    "cached_if_verified",
    "require_cached",
    "verify_path",
]
