import pathlib
import re

import appdirs
import pytest

from bookshelf.constants import DATA_FORMAT_VERSION
from bookshelf.errors import UnknownBook, UnknownVersion
from bookshelf.shelf import BookShelf, LocalBook


@pytest.fixture()
def shelf(local_bookshelf):
    shelf = BookShelf(path=local_bookshelf)
    return shelf


def test_local_cache():
    shelf = BookShelf()

    exp = pathlib.Path(appdirs.user_cache_dir()) / "bookshelf" / DATA_FORMAT_VERSION
    assert shelf.path == exp


def test_load_missing(shelf):
    with pytest.raises(UnknownBook, match=re.escape("No metadata for 'missing'")):
        shelf.load("missing")


def test_load_missing_version(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get("/v0.1.0/test/v1.1.1/datapackage.json", status_code=404)
    with pytest.raises(UnknownVersion, match="Could not find test@v1.1.1"):
        shelf.load("test", "v1.1.1")

    with pytest.raises(UnknownVersion, match="Could not find test@v1.1.1"):
        shelf.load("test", "v1.1.1", force=True)


def test_load(remote_bookshelf, shelf):
    book = shelf.load("test")
    assert book.version == "v1.1.0"

    book = shelf.load("test", "v1.1.0")
    assert book.version == "v1.1.0"

    book = shelf.load("test", "v1.0.0")
    assert book.version == "v1.0.0"


def test_load_with_cached(remote_bookshelf, local_bookshelf):
    shelf = BookShelf(path=local_bookshelf)
    shelf.load("test")

    remote_bookshelf.mocker.reset()
    remote_bookshelf.register("test", "v1.2.1")

    shelf = BookShelf(path=local_bookshelf)
    shelf.load("test", "v1.1.0")
    assert remote_bookshelf.mocker.call_count == 0

    shelf.load("test", "v1.2.1")
    assert remote_bookshelf.mocker.call_count == 1


def test_save(shelf):
    book = LocalBook.create_new("test", "v1.0.0")
    with pytest.raises(NotImplementedError):
        shelf.save(book)


def test_is_available(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get("/v0.1.0/other/volume.json", status_code=404)

    assert shelf.is_available("test", "v1.0.0")
    assert shelf.is_available("test", "v1.1.0")

    assert not shelf.is_available("test", "v1.1.1")
    assert not shelf.is_available("other", "v1.1.0")


def test_is_available_any_version(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get("/v0.1.0/other/volume.json", status_code=404)

    assert shelf.is_available("test")
    assert not shelf.is_available("other")


def test_is_cached(shelf):
    book = LocalBook.create_new("test", "v1.0.0", local_bookshelf=shelf.path)

    assert shelf.is_cached(book.name, book.version)
    assert not shelf.is_cached(book.name, "v1.0.1")
    assert not shelf.is_cached("other", "v1.0.1")
