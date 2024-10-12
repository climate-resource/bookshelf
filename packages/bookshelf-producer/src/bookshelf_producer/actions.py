"""
Actions that can be performed on the bookshelf
"""

import os
from collections.abc import Iterable
from logging import getLogger
from typing import TYPE_CHECKING, cast

import boto3
import datapackage
import requests

from bookshelf import BookShelf, LocalBook
from bookshelf.constants import DATA_FORMAT_VERSION
from bookshelf.errors import UploadError
from bookshelf.schema import BookVersion, VolumeMeta
from bookshelf.shelf import fetch_volume_meta
from bookshelf.utils import get_env_var
from bookshelf_producer.constants import DEFAULT_S3_BUCKET

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

logger = getLogger(__name__)


def _upload_file(s3: "S3Client", bucket: str, key: str, fname: str) -> None:
    try:
        logger.info(f"Uploading {fname} to {bucket} - {key}")
        s3.upload_file(fname, bucket, key, ExtraArgs={"ACL": "public-read"})
    except boto3.exceptions.S3UploadFailedError as s3_error:
        msg = f"Failed to upload {fname} to s3"
        logger.exception(msg)
        raise UploadError(msg) from s3_error


def _update_volume_meta(book: LocalBook, remote_bookshelf: str) -> str:
    try:
        volume_meta = fetch_volume_meta(book.name, remote_bookshelf, book.local_bookshelf, force=True)
    except requests.exceptions.HTTPError:
        volume_meta = VolumeMeta(name=book.name, license="", versions=[])

    meta_fname = str(book.local_bookshelf / book.name / "volume.json")
    volume_meta.versions.append(
        BookVersion(
            **{
                "version": book.version,
                "edition": book.edition,
                "url": book.url(),
                "hash": book.hash(),
                "private": book.metadata().get("private", False),
            }
        )
    )
    with open(meta_fname, "w") as file_handle:
        file_handle.write(volume_meta.json())

    return meta_fname


def publish(shelf: BookShelf, book: LocalBook, force: bool = False) -> None:
    """
    Publish a book to the remote bookshelf

    Parameters
    ----------
    book : LocalBook
        Book to upload
    force : bool
        If True, overwrite any existing data

    Raises
    ------
    UploadError
        Unable to upload the book to the remote bookshelf. See error message for
        more information about how to resolve this issue.
    """
    if shelf.is_available(book.name, book.version):
        remote_book = shelf.load(book.name, book.version)

        if remote_book.edition >= book.edition:
            msg = (
                "Edition value has not been increased (remote:"
                f" {remote_book.long_version()}, local: {book.long_version()})"
            )
            if not force:
                raise UploadError(msg)
            logger.error(msg)
        logger.warning("Uploading a new edition of an existing book")
    files = book.files()

    # Check if additional files are going to be uploaded
    resources = book.as_datapackage().resources
    resource_fnames = [
        resource.descriptor["filename"] for resource in cast(Iterable[datapackage.Resource], resources)
    ]
    for resource_file in files:
        fname = os.path.basename(resource_file)
        if fname == "datapackage.json":
            continue
        if fname not in resource_fnames:
            raise UploadError(f"Non-resource file {fname} found in book")

    # Upload using boto3 by default for testing
    # Maybe support other upload methods in future

    s3 = boto3.client("s3")
    bucket = get_env_var("BUCKET", add_prefix=True, default=DEFAULT_S3_BUCKET)
    prefix = get_env_var("BUCKET_PREFIX", add_prefix=True, default=DATA_FORMAT_VERSION)

    logger.info(f"Beginning to upload {book.name}@{book.version}")
    for resource_file in files:
        key = "/".join(
            (
                prefix,
                book.name,
                book.long_version(),
                os.path.basename(resource_file),
            )
        )
        _upload_file(s3, bucket, key, resource_file)

    # Update the metadata with the latest version information
    # Note that this doesn't have any guardrails and is susceptible to race conditions
    # Shouldn't be a problem for testing, but shouldn't be used in production
    meta_fname = _update_volume_meta(book, shelf.remote_bookshelf)
    key = "/".join((prefix, book.name, os.path.basename(meta_fname)))
    _upload_file(s3, bucket, key, meta_fname)

    logger.info(f"Book {book.name}@{book.version} ed.{book.edition} uploaded successfully")
