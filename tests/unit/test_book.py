import pytest
from bookshelf.book import Book, fetch, _fetch_volume_meta


def test_fetch_meta(local_bookshelf, remote_bookshop):
    _fetch_volume_meta("test", remote_bookshop.url(), local_bookshelf=local_bookshelf)
