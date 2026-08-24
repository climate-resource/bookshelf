"""Async resource fetching must never hash a file on the event loop.

Hashing a multi gigabyte climate dataset takes seconds,
so doing it inline stalls every other task on the loop.
The cache hit path was already careful about this and the download path was not,
which is the drift these tests pin down.
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest

from bookshelf._consume import resources
from bookshelf._consume.integrity import HashMismatchError
from bookshelf._consume.resources import AsyncResource
from bookshelf.cache import ContentCache

CONTENT = b"year,value\n2020,1.0\n"
TRACKING_ID = "11111111-2222-3333-4444-555555555555"


def _content_hash(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class _Metadata:
    """The two attributes the fetch path reads off a resource record."""

    def __init__(self, content_hash: str) -> None:
        self.hash = content_hash
        self.type = "timeseries"


class _Download:
    def __init__(self) -> None:
        self.presigned_url = "https://storage.test/object"


class _FakeClient:
    """Serves one object, writing it straight to the destination path."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.downloads = 0

    async def get_resource_download_async(self, tracking_id: Any) -> _Download:
        return _Download()

    async def stream_url_to_path_async(self, url: str, destination: Path) -> None:
        self.downloads += 1
        destination.write_bytes(self._payload)


@pytest.fixture
def offloaded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every function handed to a worker thread, and still run it."""
    names: list[str] = []
    original = asyncio.to_thread

    async def spy(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        names.append(getattr(func, "__name__", repr(func)))
        return await original(func, *args, **kwargs)

    monkeypatch.setattr(resources.asyncio, "to_thread", spy)
    return names


def _resource(tmp_path: Path, client: _FakeClient, content_hash: str) -> AsyncResource:
    return AsyncResource(
        client,  # type: ignore[arg-type]
        ContentCache(base_dir=tmp_path),
        TRACKING_ID,
        metadata=_Metadata(content_hash),  # type: ignore[arg-type]
    )


async def test_a_downloaded_file_is_verified_off_the_event_loop(
    tmp_path: Path, offloaded: list[str]
) -> None:
    client = _FakeClient(CONTENT)
    resource = _resource(tmp_path, client, _content_hash(CONTENT))

    path = await resource.as_path()

    assert path.read_bytes() == CONTENT
    assert client.downloads == 1
    assert "verify_path" in offloaded, (
        "the freshly downloaded file was hashed on the event loop, "
        f"only these ran in a worker thread: {offloaded}"
    )


async def test_a_cache_hit_is_verified_off_the_event_loop(
    tmp_path: Path, offloaded: list[str]
) -> None:
    content_hash = _content_hash(CONTENT)
    cache = ContentCache(base_dir=tmp_path)
    cache.put(content_hash, CONTENT)
    client = _FakeClient(CONTENT)
    resource = AsyncResource(
        client,  # type: ignore[arg-type]
        cache,
        TRACKING_ID,
        metadata=_Metadata(content_hash),  # type: ignore[arg-type]
    )

    path = await resource.as_path()

    assert path.read_bytes() == CONTENT
    assert client.downloads == 0
    assert "cached_if_verified" in offloaded


async def test_a_corrupt_download_still_raises_and_is_not_cached(tmp_path: Path) -> None:
    declared = _content_hash(b"the resource the server promised")
    client = _FakeClient(b"something else entirely")
    resource = _resource(tmp_path, client, declared)

    with pytest.raises(HashMismatchError):
        await resource.as_path()

    assert list(tmp_path.iterdir()) == [], "a file failing verification must not enter the cache"
