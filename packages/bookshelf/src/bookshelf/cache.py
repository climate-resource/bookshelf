"""Content addressed local cache for downloaded resources."""

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from platformdirs import user_cache_dir

DEFAULT_MAX_BYTES = 5 * 1024**3


def default_cache_dir() -> Path:
    """Return the cache directory: ``$BOOKSHELF_CACHE_DIR``, or the platform default."""
    override = os.environ.get("BOOKSHELF_CACHE_DIR")
    if override:
        return Path(override)
    return Path(user_cache_dir("bookshelf", "climateresource")) / "content"


@dataclass(frozen=True, slots=True)
class CacheSummary:
    """A point-in-time description of the cache contents."""

    path: Path
    entries: int
    total_bytes: int
    max_bytes: int
    oldest_mtime: float | None
    newest_mtime: float | None


class ContentCache:
    """A small disk cache keyed only by canonical content hash."""

    def __init__(self, base_dir: Path | None = None, *, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else default_cache_dir()
        self.max_bytes = max_bytes
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get(self, content_hash: str) -> Path | None:
        """Return the cached path, or ``None`` when the hash is absent."""
        path = self._path_for(content_hash)
        if not path.is_file():
            return None
        path.touch()
        return path

    def put(self, content_hash: str, content: bytes) -> Path:
        """Atomically store content under its hash and enforce the size cap."""
        with self.stage(content_hash) as temporary:
            temporary.write_bytes(content)
        return self._path_for(content_hash)

    @contextmanager
    def stage(self, content_hash: str) -> Iterator[Path]:
        """Yield a unique staging path and atomically commit it on success."""
        path = self._path_for(content_hash)
        temporary = self.base_dir / f"{path.name}.{uuid4().hex}.tmp"
        try:
            yield temporary
            temporary.replace(path)
            self.evict_lru()
        finally:
            temporary.unlink(missing_ok=True)

    def discard(self, content_hash: str) -> None:
        """Remove one invalid cache entry if it exists."""
        self._path_for(content_hash).unlink(missing_ok=True)

    def _entries(self) -> list[Path]:
        # Only digest-named files count as entries, so prune and clear
        # never touch foreign files in a user-supplied cache directory.
        digest_length = hashlib.sha256().digest_size * 2
        return [
            path
            for path in self.base_dir.iterdir()
            if path.is_file()
            and len(path.name) == digest_length
            and all(character in "0123456789abcdef" for character in path.name)
        ]

    def summary(self) -> CacheSummary:
        """Describe the cache: entry count, total bytes, age range and cap."""
        entries = self._entries()
        stats = [path.stat() for path in entries]
        return CacheSummary(
            path=self.base_dir,
            entries=len(entries),
            total_bytes=sum(stat.st_size for stat in stats),
            max_bytes=self.max_bytes,
            oldest_mtime=min((stat.st_mtime for stat in stats), default=None),
            newest_mtime=max((stat.st_mtime for stat in stats), default=None),
        )

    def evict_lru(self, max_bytes: int | None = None) -> int:
        """Remove least recently used entries until the cache fits the cap.

        ``max_bytes`` overrides the configured cap for this eviction only.
        """
        cap = self.max_bytes if max_bytes is None else max_bytes
        entries = sorted(self._entries(), key=lambda path: path.stat().st_mtime)
        total = sum(path.stat().st_size for path in entries)
        freed = 0
        for path in entries:
            if total - freed <= cap:
                break
            size = path.stat().st_size
            path.unlink()
            freed += size
        return freed

    def clear(self) -> int:
        """Remove every entry and return the number of bytes freed."""
        freed = 0
        for path in self._entries():
            freed += path.stat().st_size
            path.unlink()
        return freed

    def _path_for(self, content_hash: str) -> Path:
        algorithm, separator, digest = content_hash.partition(":")
        if (
            algorithm != "sha256"
            or not separator
            or len(digest) != hashlib.sha256().digest_size * 2
        ):
            raise ValueError(f"unsupported content hash {content_hash!r}")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError(f"invalid content hash {content_hash!r}") from exc
        return self.base_dir / digest.lower()


__all__ = ["CacheSummary", "ContentCache", "DEFAULT_MAX_BYTES", "default_cache_dir"]
