import re

import pytest
from bookshelf.errors import UnknownBook, UnknownVersion
from bookshelf.shelf import BookShelf


def test_load_missing(local_bookshelf):
    shelf = BookShelf(path=local_bookshelf, remote_bookshelf="http://example.com")
    with pytest.raises(UnknownBook, match=re.escape("No metadata for 'missing'")):
        shelf.load("missing")

    with pytest.raises(UnknownVersion, match="Could not find test@v1.1.1"):
        shelf.load("test", "v1.1.1")


def test_load(remote_bookshelf, local_bookshelf):
    shelf = BookShelf(path=local_bookshelf)

    book = shelf.load("test")
    assert book.version == "v1.1.0"

    book = shelf.load("test", "v1.1.0")
    assert book.version == "v1.1.0"

    book = shelf.load("test", "v1.0.0")
    assert book.version == "v1.0.0"


def test_load_with_cached(remote_bookshelf, local_bookshelf):
    remote_bookshelf.register("test", "v1.2.1")

    shelf = BookShelf(path=local_bookshelf)
    shelf.load("test")

    remote_bookshelf.mocker.reset()

    shelf = BookShelf(path=local_bookshelf)
    shelf.load("test", "v1.2.1")
    assert remote_bookshelf.mocker.call_count == 0
