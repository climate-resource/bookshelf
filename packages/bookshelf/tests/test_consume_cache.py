"""Naming a cache entry and recognising one on disk have to agree.

``_path_for`` decides the filename and ``_entries`` decides what counts as one.
A digest the first accepts and the second does not
becomes a file that the summary, the eviction and the clear all step over,
so it occupies the cache forever without ever counting towards the cap.
"""

from pathlib import Path

import pytest

from bookshelf.cache import ContentCache

DIGEST = "a" * 64


@pytest.fixture
def cache(tmp_path: Path) -> ContentCache:
    return ContentCache(base_dir=tmp_path)


@pytest.mark.parametrize(
    "digest",
    [
        pytest.param("a" * 31 + "_" + "a" * 32, id="interior-underscore"),
        pytest.param(" " + "a" * 63, id="leading-space"),
        pytest.param("+" + "a" * 63, id="leading-plus"),
        pytest.param("-" + "a" * 63, id="leading-minus"),
    ],
)
def test_a_digest_that_is_not_plain_hex_is_rejected(cache: ContentCache, digest: str) -> None:
    """``int(digest, 16)`` used to accept all of these, which named unfindable files."""
    with pytest.raises(ValueError, match="invalid content hash"):
        cache.put(f"sha256:{digest}", b"payload")


def test_an_upper_case_digest_is_normalised_rather_than_rejected(cache: ContentCache) -> None:
    """The server's canonical form is lower case, but the cache has always folded case."""
    cache.put(f"sha256:{DIGEST.upper()}", b"payload")

    assert cache.get(f"sha256:{DIGEST}") is not None
    assert cache.summary().entries == 1


@pytest.mark.parametrize(
    "content_hash",
    [
        pytest.param(f"md5:{DIGEST}", id="wrong-algorithm"),
        pytest.param(DIGEST, id="no-separator"),
        pytest.param("sha256:abc", id="too-short"),
    ],
)
def test_a_malformed_content_hash_is_rejected(cache: ContentCache, content_hash: str) -> None:
    with pytest.raises(ValueError, match="unsupported content hash"):
        cache.put(content_hash, b"payload")


def test_every_stored_entry_is_visible_to_the_summary(cache: ContentCache) -> None:
    """The property the two predicates exist to keep: what is stored can be found again."""
    cache.put(f"sha256:{DIGEST}", b"payload")
    cache.put(f"sha256:{('b' * 64).upper()}", b"other")

    assert cache.summary().entries == 2
    assert cache.clear() == len(b"payload") + len(b"other")
    assert cache.summary().entries == 0
