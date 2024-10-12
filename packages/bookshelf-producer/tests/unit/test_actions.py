import io
import json
import logging
import os
import re

import boto3
import boto3.exceptions
import pytest
from moto import mock_aws

from bookshelf.constants import DATA_FORMAT_VERSION
from bookshelf.errors import UploadError
from bookshelf.shelf import BookShelf, LocalBook
from bookshelf_producer.actions import _update_volume_meta, publish
from bookshelf_producer.notebook import NotebookMetadata


@pytest.fixture()
def shelf(local_bookshelf):
    shelf = BookShelf(path=local_bookshelf)
    return shelf


def get_meta(conn, bucket, pkg):
    volume_meta_contents = io.BytesIO()
    conn.Object(bucket, f"/this/prefix/{pkg}/volume.json").download_fileobj(volume_meta_contents)
    volume_meta_contents.seek(0)
    return json.load(volume_meta_contents)


def setup_upload_bucket(remote_bookshelf, monkeypatch):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/new-package/volume.json", status_code=404)

    bucket = "test-bucket"
    prefix = "/this/prefix"
    monkeypatch.setenv("BOOKSHELF_BUCKET", bucket)
    monkeypatch.setenv("BOOKSHELF_BUCKET_PREFIX", prefix)

    conn = boto3.resource("s3", region_name="us-east-1")
    conn.create_bucket(Bucket=bucket)

    return conn


@mock_aws
def test_publish(shelf, remote_bookshelf, monkeypatch, caplog, example_data):
    conn = setup_upload_bucket(remote_bookshelf, monkeypatch)

    book = LocalBook.create_new("new-package", "v1.1.1")
    book.add_timeseries("example", example_data)

    with caplog.at_level(logging.INFO):
        publish(shelf, book)

    # Check that files uploaded
    bucket = os.environ["BOOKSHELF_BUCKET"]
    conn.Object(bucket, "/this/prefix/new-package/v1.1.1_e001/datapackage.json").load()
    assert (
        conn.Object(bucket, "/this/prefix/new-package/v1.1.1_e001/datapackage.json")
        .Acl()
        .grants[1]["Permission"]
        == "READ"
    )

    conn.Object(
        bucket, "/this/prefix/new-package/v1.1.1_e001/new-package_v1.1.1_e001_example_long.csv.gz"
    ).load()

    volume_meta = get_meta(conn, bucket, "new-package")
    assert len(volume_meta["versions"]) == 1
    assert volume_meta["versions"][-1]["version"] == "v1.1.1"

    assert "Book new-package@v1.1.1 ed.1 uploaded successfully" in caplog.text


@mock_aws
def test_publish_new_version(shelf, remote_bookshelf, monkeypatch, caplog, example_data):
    conn = setup_upload_bucket(remote_bookshelf, monkeypatch)

    book = LocalBook.create_new("test", "v1.1.1", edition=25)

    with caplog.at_level(logging.INFO):
        publish(shelf, book)

    # Check that files uploaded
    bucket = os.environ["BOOKSHELF_BUCKET"]
    conn.Object(bucket, "/this/prefix/test/v1.1.1_e025/datapackage.json").load()

    volume_meta = get_meta(conn, bucket, "test")
    assert len(volume_meta["versions"]) == 3  # 2 existing in volume.json + one extra
    assert volume_meta["versions"][-1]["version"] == "v1.1.1"

    assert "Book test@v1.1.1 ed.25 uploaded successfully" in caplog.text


@pytest.mark.parametrize("edition", [2, 900])
@mock_aws
def test_publish_new_edition(  # noqa
    shelf,
    remote_bookshelf,
    monkeypatch,
    caplog,
    example_data,
    edition,
):
    conn = setup_upload_bucket(remote_bookshelf, monkeypatch)
    book = LocalBook.create_new("test", "v1.1.0", edition=edition)

    with caplog.at_level(logging.INFO):
        publish(shelf, book)

    # Check that files uploaded
    bucket = os.environ["BOOKSHELF_BUCKET"]
    conn.Object(bucket, f"/this/prefix/test/v1.1.0_e{edition:03}/datapackage.json").load()

    volume_meta = get_meta(conn, bucket, "test")
    assert len(volume_meta["versions"]) == 3  # 2 existing in volume.json + one extra
    assert volume_meta["versions"][-1]["version"] == "v1.1.0"
    assert volume_meta["versions"][-1]["edition"] == edition

    assert "Uploading a new edition of an existing book" in caplog.text
    assert f"Book test@v1.1.0 ed.{edition} uploaded successfully" in caplog.text


@mock_aws
def test_publish_wrong_permissions(shelf, remote_bookshelf, monkeypatch, caplog):
    setup_upload_bucket(remote_bookshelf, monkeypatch)

    # Modify bucket used (this bucket hasn't been created)
    bucket = "test-bucket-wrong"
    monkeypatch.setenv("BOOKSHELF_BUCKET", bucket)

    caplog.set_level(logging.ERROR)

    book = LocalBook.create_new("new-package", "v1.0.0")
    with pytest.raises(UploadError, match=re.escape(f"Failed to upload {book.files()[0]} to s3")):
        publish(shelf, book)

    assert "NoSuchBucket" in caplog.text
    assert bucket in caplog.text


def test_publish_existing(shelf, remote_bookshelf):
    book = LocalBook.create_new("test", "v1.0.0", 1)

    with pytest.raises(
        UploadError,
        match=re.escape("Edition value has not been increased (remote: v1.0.0_e001, local:" " v1.0.0_e001)"),
    ):
        publish(shelf, book, force=False)


@mock_aws
def test_publish_existing_forced(shelf, remote_bookshelf, monkeypatch, caplog):
    setup_upload_bucket(remote_bookshelf, monkeypatch)

    book = LocalBook.create_new("new-package", "v1.0.0", 1)

    with caplog.at_level(logging.INFO):
        publish(shelf, book, force=True)

    assert "Book new-package@v1.0.0 ed.1 uploaded successfully" in caplog.text


def test_publish_extra_file(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/new-package/volume.json", status_code=404)

    book = LocalBook.create_new("new-package", "v1.0.0")
    open(book.local_fname("extra_file.txt"), "w").close()

    with pytest.raises(UploadError, match="Non-resource file extra_file.txt found in book"):
        publish(shelf, book)


def test_update_volume_meta(local_bookshelf, remote_bookshelf):
    book = LocalBook.create_from_metadata(
        NotebookMetadata(
            name="test",
            version="v2_private",
            edition=1,
            license="",
            source_file="",
            private=True,
            dataset={"author": "", "files": []},
            metadata={},
            data_dictionary=[
                {
                    "name": "test",
                    "description": "test description",
                    "type": "string",
                    "allowed_NA": False,
                    "required_column": True,
                    "controlled_vocabulary": [{"value": "test", "description": "test description"}],
                }
            ],
        ),
        local_bookshelf=local_bookshelf,
    )

    res = _update_volume_meta(book, os.environ["BOOKSHELF_REMOTE"])
    with open(res) as fh:
        contents = json.load(fh)

    assert contents["versions"][-1]["version"] == "v2_private"
    assert contents["versions"][-1]["private"]
