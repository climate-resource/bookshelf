import io
import json
import pathlib
import platform
import re

import platformdirs
import pytest

from bookshelf.constants import DATA_FORMAT_VERSION
from bookshelf.errors import UnknownBook, UnknownVersion
from bookshelf.shelf import BookShelf, LocalBook


@pytest.fixture()
def shelf(local_bookshelf):
    shelf = BookShelf(path=local_bookshelf)
    return shelf


def get_meta(conn, bucket, pkg):
    volume_meta_contents = io.BytesIO()
    conn.Object(bucket, f"/this/prefix/{pkg}/volume.json").download_fileobj(volume_meta_contents)
    volume_meta_contents.seek(0)
    return json.load(volume_meta_contents)


def test_local_cache(monkeypatch):
    # Override the local_bookshelf fixture
    monkeypatch.delenv("BOOKSHELF_CACHE_LOCATION")

    shelf = BookShelf()

    if platform.system() == "Windows":
        exp = pathlib.Path(platformdirs.user_cache_dir()) / "bookshelf" / "Cache" / DATA_FORMAT_VERSION
    else:
        exp = pathlib.Path(platformdirs.user_cache_dir()) / "bookshelf" / DATA_FORMAT_VERSION
    assert shelf.path == exp


def test_load_missing(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/missing/volume.json", status_code=404)

    with pytest.raises(UnknownBook, match=re.escape("No metadata for 'missing'")):
        shelf.load("missing")


def test_load_missing_version(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/test/v1.1.1/datapackage.json", status_code=404)
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
    remote_bookshelf.register("test", "v1.1.0", 2)
    remote_bookshelf.register("test", "v1.2.1", 1)

    shelf = BookShelf(path=local_bookshelf)
    shelf.load("test", "v1.1.0", 1)
    assert remote_bookshelf.mocker.call_count == 0

    # Not providing an edition causes a fetch of the volume and datapackage
    book = shelf.load("test", "v1.1.0")
    assert book.edition == 2
    assert remote_bookshelf.mocker.call_count == 2

    # A cache miss causes a fetch of the data package
    shelf.load("test", "v1.2.1", 1)
    assert remote_bookshelf.mocker.call_count == 3

    # Not providing a version/edition always causes a fetch
    shelf.load("test")
    assert remote_bookshelf.mocker.call_count == 4


def test_is_available(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/other/volume.json", status_code=404)

    assert shelf.is_available("test", "v1.0.0")
    assert shelf.is_available("test", "v1.1.0")

    assert not shelf.is_available("test", "v1.1.1")
    assert not shelf.is_available("other", "v1.1.0")


def test_is_available_any_version(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/other/volume.json", status_code=404)

    assert shelf.is_available("test")
    assert not shelf.is_available("other")


def test_is_cached(shelf):
    book = LocalBook.create_new("test", "v1.0.0", edition=1, local_bookshelf=shelf.path)

    assert shelf.is_cached(book.name, book.version, edition=1)
    assert not shelf.is_cached(book.name, "v1.0.1", 1)
    assert not shelf.is_cached("other", "v1.0.1", 1)


def test_list_versions(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/other/volume.json", status_code=404)

    assert shelf.list_versions("test") == ["v1.0.0", "v1.1.0"]
    with pytest.raises(UnknownBook):
        shelf.list_versions("other")


@pytest.mark.xfail(reason="Not implemented")
def test_list_name(shelf):
    assert shelf.list_books() == ["test"]


def test_private_list(remote_bookshelf, local_bookshelf):
    remote_bookshelf.register("test", "v2_private", 1, private=True)
    shelf = BookShelf(path=local_bookshelf)

    assert shelf.list_versions("test") == ["v1.0.0", "v1.1.0"]
    assert shelf.load("test", "v2_private")

    assert shelf.load("test").version == "v1.1.0"
