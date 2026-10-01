"""Concurrent fetches of one hash download it once, whether they race in threads, tasks or processes."""

import asyncio
import hashlib
import multiprocessing
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bookshelf import BookshelfError, HashMismatchError
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


async def test_racing_tasks_download_once(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path / "cache")
    downloads = 0

    async def download(destination: Path) -> None:
        nonlocal downloads
        downloads += 1
        await asyncio.sleep(0.2)
        destination.write_bytes(CONTENT)

    paths = await asyncio.gather(*(cache.fetch_async(CONTENT_HASH, download) for _ in range(4)))

    assert len(set(paths)) == 1
    assert downloads == 1


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


async def test_a_cache_removed_mid_session_is_recreated_async(tmp_path: Path) -> None:
    base = tmp_path / "cache"
    cache = ContentCache(base)
    shutil.rmtree(base)

    async def download(path: Path) -> None:
        path.write_bytes(CONTENT)

    fetched = await cache.fetch_async(CONTENT_HASH, download)

    assert fetched.read_bytes() == CONTENT


@pytest.mark.parametrize("relative", ["file", "file/below"])
def test_a_cache_path_that_is_a_file_raises_a_bookshelf_error(
    tmp_path: Path, relative: str
) -> None:
    (tmp_path / "file").write_text("not a directory")

    with pytest.raises(BookshelfError, match="cache directory"):
        ContentCache(tmp_path / relative)
