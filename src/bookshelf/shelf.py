"""
BookShelf

A BookShelf is a collection of Books
"""
import json
import logging
import os
import pathlib
from typing import Iterable, Optional, Union, cast

import boto3
import boto3.exceptions
import datapackage
import requests.exceptions

from bookshelf.book import LocalBook
from bookshelf.errors import UnknownBook, UnknownVersion, UploadError
from bookshelf.schema import BookVersion, Version, VolumeMeta
from bookshelf.utils import (
    build_url,
    create_local_cache,
    fetch_file,
    get_env_var,
    get_remote_bookshelf,
)

logger = logging.getLogger(__name__)


def _fetch_volume_meta(
    name: str,
    remote_bookshelf: str,
    local_bookshelf: pathlib.Path,
    force: bool = True,
) -> VolumeMeta:
    """
    Fetch information about the books available for a given volume

    Parameters
    ----------
    name : str
        Name of the volume to fetch
    remote_bookshelf : str
        URL for the remote bookshelf
    local_bookshelf : pathlib.Path
        Local path where downloaded books will be stored.

        Must be a writable directory
    force: bool
        If True metadata is always fetched from the remote bookshelf

    Returns
    -------
    VolumeMeta
    """
    fname = "volume.json"

    local_fname = local_bookshelf / name / fname
    url = build_url(remote_bookshelf, name, fname)

    fetch_file(url, local_fname, force=force)

    with open(str(local_fname)) as file_handle:
        data = json.load(file_handle)

    return VolumeMeta(**data)


def _upload_file(s3, bucket, key, fname):  # pylint: disable=invalid-name
    try:
        logger.info(f"Uploading {fname}")
        s3.upload_file(fname, bucket, key, ExtraArgs={"ACL": "public-read"})
    except boto3.exceptions.S3UploadFailedError as s3_error:
        logger.exception(s3_error, exc_info=False)
        raise UploadError(f"Failed to upload {fname} to s3") from s3_error


def _update_volume_meta(book: LocalBook, remote_bookshelf: str) -> str:
    try:
        volume_meta = _fetch_volume_meta(
            book.name, remote_bookshelf, book.local_bookshelf, force=True
        )
    except requests.exceptions.HTTPError:
        volume_meta = VolumeMeta(name=book.name, license="", versions=[])

    meta_fname = str(book.local_bookshelf / book.name / "volume.json")
    volume_meta.versions.append(
        BookVersion(**{"version": book.version, "url": book.url(), "hash": book.hash()})
    )
    with open(meta_fname, "w") as file_handle:
        file_handle.write(volume_meta.json())

    return meta_fname


class BookShelf:
    """
    A BookShelf stores a number of Books

    If a Book isn't available locally, it will be queried from the remote bookshelf.

    Books can be fetched using :func:`load` by name. Specific versions of a book can be
    pinned if needed otherwise the latest version of the book is loaded.
    """

    def __init__(
        self,
        path: Union[str, pathlib.Path, None] = None,
        remote_bookshelf: Optional[str] = None,
    ):
        if path is None:
            path = create_local_cache(path)
        self.path = pathlib.Path(path)
        self.remote_bookshelf = get_remote_bookshelf(remote_bookshelf)

    def load(
        self, name: str, version: Optional[str] = None, force: bool = False
    ) -> LocalBook:
        """
        Load a book

        If the book's metadata does not exist locally or an unknown version is requested
        the remote bookshelf is queried, otherwise the local metadata is used.

        Parameters
        ----------
        name: str
            Name of the volume to load
        version: str
            Version to load

            If no version is provided, the latest version is returned
        force: bool
            If True, redownload the book metadata

        Raises
        ------
        UnknownVersion
            The requested version is not available for the selected volume
        UnknownBook
            An invalid volume is requested

        Returns
        -------
        :class:`LocalBook`
            A book from which the resources can be accessed
        """
        if version is None or force:
            version = self._resolve_version(name, version)

        metadata_fragment = os.path.join(name, version, "datapackage.json")
        metadata_fname = self.path / metadata_fragment

        if not metadata_fname.exists():
            try:
                url = build_url(self.remote_bookshelf, metadata_fragment)
                fetch_file(
                    url,
                    local_fname=metadata_fname,
                    known_hash=None,
                    force=force,
                )
            except requests.exceptions.HTTPError as http_error:
                raise UnknownVersion(name, version) from http_error

        if not metadata_fname.exists():
            raise AssertionError()  # noqa

        return LocalBook(name, version, local_bookshelf=self.path)

    def is_available(self, name: str, version: Version = None) -> bool:
        """
        Check if a Book is available from the remote bookshelf

        Parameters
        ----------
        name : str
            Name of the volume to check
        version : str
            Version of the volume to check

            If no version is provided, then check if any Book's with a matching name
            have been uploaded.

        Returns
        -------
        bool
            True if a Book with a matching name and version exists on the remote bookshelf
        """
        try:
            self._resolve_version(name, version)
            return True
        except (UnknownBook, UnknownVersion):
            return False

    def is_cached(self, name: str, version: str) -> bool:
        """
        Check if a book with a matching name/version is cached on the local bookshelf

        Parameters
        ----------
        name : str
            Name of the volume to check
        version : str
            Version of the volume to check

        Returns
        -------
        bool
            True if a matching book is cached locally
        """
        try:
            # Check if the metadata for the book can be successfully read
            book = LocalBook(name, version, local_bookshelf=self.path)
            book.metadata()
            return True
        except FileNotFoundError:
            return False

    def save(self, book: LocalBook, force: bool = False) -> None:
        """
        Save a book to the remote bookshelf

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
        if self.is_available(book.name, book.version):
            if not force:
                raise UploadError("Book with the same version already exists")
            logger.warning(
                "Book with the same version already exists on remote bookshelf"
            )
        files = book.files()

        # Check if additional files are going to be uploaded
        resources = book.metadata().resources
        resource_fnames = [
            resource.descriptor["filename"]
            for resource in cast(Iterable[datapackage.Resource], resources)
        ]
        for resource_file in files:
            fname = os.path.basename(resource_file)
            if fname == "datapackage.json":
                continue
            if fname not in resource_fnames:
                raise UploadError(f"Non-resource file {fname} found in book")

        # Upload using boto3 by default for testing
        # Maybe support other upload methods in future

        s3 = boto3.client("s3")  # pylint: disable=invalid-name
        bucket = get_env_var("BUCKET", add_prefix=True)
        prefix = get_env_var("BUCKET_PREFIX", add_prefix=True)

        logger.info(f"Beginning to upload {book.name}@{book.version}")
        for resource_file in files:
            key = os.path.join(
                prefix, book.name, book.version, os.path.basename(resource_file)
            )
            _upload_file(s3, bucket, key, resource_file)

        # Update the metadata with the latest version information
        # Note that this doesn't have any guardrails and is susceptible to race conditions
        # Shouldn't be a problem for testing, but shouldn't be used in production
        meta_fname = _update_volume_meta(book, self.remote_bookshelf)
        key = os.path.join(prefix, book.name, os.path.basename(meta_fname))
        _upload_file(s3, bucket, key, meta_fname)

        logger.info(f"Book {book.name}@{book.version} uploaded successfully")

    def _resolve_version(self, name: str, version: Version = None) -> str:
        # Update the package metadata
        try:
            meta = _fetch_volume_meta(name, self.remote_bookshelf, self.path)
        except requests.exceptions.HTTPError as http_error:
            raise UnknownBook(f"No metadata for {repr(name)}") from http_error

        if version is None:
            return meta.versions[-1].version

        # Verify that the version exists
        for item in meta.versions:
            if item.version == version:
                return version
        raise UnknownVersion(name, version)
