"""Concurrent fetches of one hash download it once, whether they race in threads, tasks or processes."""

import errno
import hashlib
import multiprocessing
import os
import shutil
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bookshelf import BookshelfError, CacheDirectoryError, HashMismatchError
from bookshelf.cache import ContentCache

CONTENT = b"year,value\n2020,1.0\n"
CONTENT_HASH = f"sha256:{hashlib.sha256(CONTENT).hexdigest()}"


def _slow_download(log: Path, destination: Path) -> None:
    # Appending is atomic enough for a count, and holding the lock a while forces the race.
    with log.open("a") as stream:
        stream.write("x")
    time.sleep(0.2)
    destination.write_bytes(CONTENT)


def _fetch_in_process(base_dir: Path, log: Path) -> None:
    ContentCache(base_dir).fetch(CONTENT_HASH, lambda path: _slow_download(log, path))


def test_a_miss_downloads_and_a_hit_does_not(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path / "cache")
    log = tmp_path / "downloads"

    first = cache.fetch(CONTENT_HASH, lambda path: _slow_download(log, path))
    second = cache.fetch(CONTENT_HASH, lambda path: _slow_download(log, path))

    assert first == second
    assert first.read_bytes() == CONTENT
    assert log.read_text() == "x"


def test_racing_threads_download_once(tmp_path: Path) -> None:
    log = tmp_path / "downloads"
    barrier = threading.Barrier(4)

    def fetch() -> Path:
        barrier.wait()
        return ContentCache(tmp_path / "cache").fetch(
            CONTENT_HASH, lambda path: _slow_download(log, path)
        )

    with ThreadPoolExecutor(4) as pool:
        paths = list(pool.map(lambda _: fetch(), range(4)))

    assert len(set(paths)) == 1
    assert log.read_text() == "x"


def test_racing_processes_download_once(tmp_path: Path) -> None:
    log = tmp_path / "downloads"
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_fetch_in_process, args=(tmp_path / "cache", log)) for _ in range(3)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    assert [worker.exitcode for worker in workers] == [0, 0, 0]
    assert log.read_text() == "x"


def test_a_mismatched_download_is_not_stored(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)

    def download(destination: Path) -> None:
        destination.write_bytes(b"tampered")

    with pytest.raises(HashMismatchError):
        cache.fetch(CONTENT_HASH, download)

    assert cache.summary().entries == 0


def test_a_cache_removed_mid_session_is_recreated(tmp_path: Path) -> None:
    base = tmp_path / "cache"
    cache = ContentCache(base)
    shutil.rmtree(base)

    fetched = cache.fetch(CONTENT_HASH, lambda path: path.write_bytes(CONTENT))

    assert fetched.read_bytes() == CONTENT


@pytest.mark.parametrize("relative", ["file", "file/below"])
def test_a_cache_path_that_is_a_file_raises_a_bookshelf_error(
    tmp_path: Path, relative: str
) -> None:
    (tmp_path / "file").write_text("not a directory")

    with pytest.raises(BookshelfError, match="cache directory"):
        ContentCache(tmp_path / relative)


def _skip_unless_modes_bind() -> None:
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        pytest.skip("mode bits do not stop this user writing")


@pytest.fixture
def read_only(tmp_path: Path) -> Iterator[Path]:
    _skip_unless_modes_bind()
    base = tmp_path / "cache"
    base.mkdir()
    base.chmod(0o555)
    yield base
    base.chmod(0o755)


def test_a_read_only_cache_raises_a_cache_directory_error(read_only: Path) -> None:
    cache = ContentCache(read_only)

    with pytest.raises(CacheDirectoryError, match=f"cache directory {read_only}"):
        cache.fetch(CONTENT_HASH, lambda path: path.write_bytes(CONTENT))


def test_a_cache_made_read_only_after_use_raises_a_cache_directory_error(tmp_path: Path) -> None:
    _skip_unless_modes_bind()
    base = tmp_path / "cache"
    cache = ContentCache(base)
    cache.fetch(CONTENT_HASH, lambda path: path.write_bytes(CONTENT))
    other = b"other"
    other_hash = f"sha256:{hashlib.sha256(other).hexdigest()}"
    for directory in (base, base / ".locks"):
        directory.chmod(0o555)
    try:
        with pytest.raises(CacheDirectoryError, match="cache directory"):
            cache.fetch(other_hash, lambda path: path.write_bytes(other))
        assert cache.fetch(CONTENT_HASH, lambda path: path.write_bytes(CONTENT)).is_file()
    finally:
        for directory in (base, base / ".locks"):
            directory.chmod(0o755)


def test_a_hit_on_a_read_only_file_system_still_serves_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = ContentCache(tmp_path / "cache")
    stored = cache.fetch(CONTENT_HASH, lambda path: path.write_bytes(CONTENT))

    def refuse(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError(errno.EROFS, os.strerror(errno.EROFS), str(self))

    monkeypatch.setattr(Path, "touch", refuse)

    assert cache.fetch(CONTENT_HASH, lambda path: path.write_bytes(b"unused")) == stored
