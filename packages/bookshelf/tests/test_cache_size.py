"""The cache size cap comes from ``max_bytes``, then ``$BOOKSHELF_CACHE_MAX_SIZE``, then 5 GiB."""

from pathlib import Path

import pytest

from bookshelf.cache import DEFAULT_MAX_BYTES, ContentCache


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        ("20GiB", 20 * 1024**3),
        ("500MB", 500 * 1000**2),
        ("1.5 gib", int(1.5 * 1024**3)),
        ("4096", 4096),
    ],
)
def test_the_cap_reads_its_size_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str, expected: int
) -> None:
    monkeypatch.setenv("BOOKSHELF_CACHE_MAX_SIZE", setting)

    assert ContentCache(tmp_path).max_bytes == expected


def test_a_cap_that_is_not_a_size_warns_and_keeps_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOKSHELF_CACHE_MAX_SIZE", "lots")

    with pytest.warns(UserWarning, match="BOOKSHELF_CACHE_MAX_SIZE"):
        cache = ContentCache(tmp_path)

    assert cache.max_bytes == DEFAULT_MAX_BYTES


def test_an_explicit_cap_wins_over_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOKSHELF_CACHE_MAX_SIZE", "20GiB")

    assert ContentCache(tmp_path, max_bytes=10).max_bytes == 10
