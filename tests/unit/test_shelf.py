import io
import json
import logging
import os
import pathlib
import re

import appdirs
import boto3
import boto3.exceptions
import moto
import pytest

from bookshelf.constants import DATA_FORMAT_VERSION
from bookshelf.errors import UnknownBook, UnknownVersion, UploadError
from bookshelf.shelf import BookShelf, LocalBook


@pytest.fixture()
def shelf(local_bookshelf):
    shelf = BookShelf(path=local_bookshelf)
    return shelf


def setup_upload_bucket(remote_bookshelf, monkeypatch):
    remote_bookshelf.mocker.get(
        f"/{DATA_FORMAT_VERSION}/new-package/volume.json", status_code=404
    )

    bucket = "test-bucket"
    prefix = "/this/prefix"
    monkeypatch.setenv("BOOKSHELF_BUCKET", bucket)
    monkeypatch.setenv("BOOKSHELF_BUCKET_PREFIX", prefix)

    conn = boto3.resource("s3", region_name="us-east-1")
    conn.create_bucket(Bucket=bucket)

    return conn


def test_local_cache(monkeypatch):
    # Override the local_bookshelf fixture
    monkeypatch.delenv("BOOKSHELF_CACHE_LOCATION")

    shelf = BookShelf()

    exp = pathlib.Path(appdirs.user_cache_dir()) / "bookshelf" / DATA_FORMAT_VERSION
    assert shelf.path == exp


def test_load_missing(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(
        f"/{DATA_FORMAT_VERSION}/missing/volume.json", status_code=404
    )

    with pytest.raises(UnknownBook, match=re.escape("No metadata for 'missing'")):
        shelf.load("missing")


def test_load_missing_version(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(
        f"/{DATA_FORMAT_VERSION}/test/v1.1.1/datapackage.json", status_code=404
    )
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


@moto.mock_s3
def test_publish(shelf, remote_bookshelf, monkeypatch, caplog, example_data):
    conn = setup_upload_bucket(remote_bookshelf, monkeypatch)

    book = LocalBook.create_new("new-package", "v1.1.1")
    book.add_timeseries("example", example_data)

    with caplog.at_level(logging.INFO):
        shelf.publish(book)

    # Check that files uploaded
    bucket = os.environ["BOOKSHELF_BUCKET"]
    conn.Object(bucket, "/this/prefix/new-package/v1.1.1_e001/datapackage.json").load()
    assert (
        conn.Object(bucket, "/this/prefix/new-package/v1.1.1_e001/datapackage.json")
        .Acl()
        .grants[1]["Permission"]
        == "READ"
    )
    conn.Object(bucket, "/this/prefix/new-package/v1.1.1_e001/example.csv").load()

    volume_meta_contents = io.BytesIO()
    conn.Object(bucket, "/this/prefix/new-package/volume.json").download_fileobj(
        volume_meta_contents
    )
    volume_meta_contents.seek(0)
    volume_meta = json.load(volume_meta_contents)

    assert len(volume_meta["versions"]) == 1
    assert volume_meta["versions"][-1]["version"] == "v1.1.1"

    assert "Book new-package@v1.1.1 ed.1 uploaded successfully" in caplog.text


@moto.mock_s3
def test_publish_new_version(
    shelf, remote_bookshelf, monkeypatch, caplog, example_data
):
    conn = setup_upload_bucket(remote_bookshelf, monkeypatch)

    book = LocalBook.create_new("test", "v1.1.1", edition=25)

    with caplog.at_level(logging.INFO):
        shelf.publish(book)

    # Check that files uploaded
    bucket = os.environ["BOOKSHELF_BUCKET"]
    conn.Object(bucket, "/this/prefix/test/v1.1.1_e025/datapackage.json").load()

    volume_meta_contents = io.BytesIO()
    conn.Object(bucket, "/this/prefix/test/volume.json").download_fileobj(
        volume_meta_contents
    )
    volume_meta_contents.seek(0)
    volume_meta = json.load(volume_meta_contents)

    assert len(volume_meta["versions"]) == 3  # 2 existing in volume.json + one extra
    assert volume_meta["versions"][-1]["version"] == "v1.1.1"

    assert "Book test@v1.1.1 ed.25 uploaded successfully" in caplog.text


@moto.mock_s3
def test_publish_wrong_permissions(shelf, remote_bookshelf, monkeypatch, caplog):
    setup_upload_bucket(remote_bookshelf, monkeypatch)

    # Modify bucket used (this bucket hasn't been created)
    bucket = "test-bucket-wrong"
    monkeypatch.setenv("BOOKSHELF_BUCKET", bucket)

    caplog.set_level(logging.ERROR)

    book = LocalBook.create_new("new-package", "v1.0.0")
    with pytest.raises(UploadError, match=f"Failed to upload {book.files()[0]} to s3"):
        shelf.publish(book)

    assert "NoSuchBucket" in caplog.text
    assert bucket in caplog.text


def test_publish_existing(shelf, remote_bookshelf):
    book = LocalBook.create_new("test", "v1.0.0", 1)

    with pytest.raises(UploadError, match="Book with the same version already exists"):
        shelf.publish(book, force=False)


@moto.mock_s3
def test_publish_existing_forced(shelf, remote_bookshelf, monkeypatch, caplog):
    setup_upload_bucket(remote_bookshelf, monkeypatch)

    book = LocalBook.create_new("new-package", "v1.0.0", 1)

    with caplog.at_level(logging.INFO):
        shelf.publish(book, force=True)

    assert "Book new-package@v1.0.0 ed.1 uploaded successfully" in caplog.text


def test_publish_extra_file(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(
        f"/{DATA_FORMAT_VERSION}/new-package/volume.json", status_code=404
    )

    book = LocalBook.create_new("new-package", "v1.0.0")
    open(book.local_fname("extra_file.txt"), "w").close()

    with pytest.raises(
        UploadError, match="Non-resource file extra_file.txt found in book"
    ):
        shelf.publish(book)


def test_is_available(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(
        f"/{DATA_FORMAT_VERSION}/other/volume.json", status_code=404
    )

    assert shelf.is_available("test", "v1.0.0")
    assert shelf.is_available("test", "v1.1.0")

    assert not shelf.is_available("test", "v1.1.1")
    assert not shelf.is_available("other", "v1.1.0")


def test_is_available_any_version(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(
        f"/{DATA_FORMAT_VERSION}/other/volume.json", status_code=404
    )

    assert shelf.is_available("test")
    assert not shelf.is_available("other")


def test_is_cached(shelf):
    book = LocalBook.create_new("test", "v1.0.0", edition=1, local_bookshelf=shelf.path)

    assert shelf.is_cached(book.name, book.version, edition=1)
    assert not shelf.is_cached(book.name, "v1.0.1", 1)
    assert not shelf.is_cached("other", "v1.0.1", 1)


def test_list_versions(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(
        f"/{DATA_FORMAT_VERSION}/other/volume.json", status_code=404
    )

    assert shelf.list_versions("test") == ["v1.0.0", "v1.1.0"]
    with pytest.raises(UnknownBook):
        shelf.list_versions("other")


@pytest.mark.xfail(reason="Not implemented")
def test_list_name(shelf):
    assert shelf.list_books() == ["test"]
