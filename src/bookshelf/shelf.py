"""
BookShelf

A BookShelf is a collection of Books
"""
import json
import logging
import os
import pathlib
from typing import Optional, Union

import requests.exceptions

from bookshelf.book import LocalBook
from bookshelf.constants import DEFAULT_BOOKSHELF
from bookshelf.errors import UnknownBook, UnknownVersion, UploadError
from bookshelf.schema import Version, VolumeMeta
from bookshelf.utils import build_url, create_local_cache, fetch_file

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

    fetch_file(url, local_fname)

    with open(str(local_fname)) as file_handle:
        data = json.load(file_handle)

    return VolumeMeta(**data)


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
        remote_bookshelf: str = DEFAULT_BOOKSHELF,
    ):
        if path is None:
            path = create_local_cache(path)
        self.path = pathlib.Path(path)
        self.remote_bookshelf = remote_bookshelf

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
            except requests.exceptions.HTTPError:
                raise UnknownVersion(name, version)

        if not metadata_fname.exists():
            raise AssertionError()  # noqa

        return LocalBook(name, version, local_bookshelf=self.path)

    def is_available(self, name, version: Version = None) -> bool:
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

    def save(self, book: LocalBook, force: bool = True) -> None:
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

        raise NotImplementedError

    def _resolve_version(self, name: str, version: Version = None) -> str:
        # Update the package metadata
        try:
            meta = _fetch_volume_meta(name, self.remote_bookshelf, self.path)
        except requests.exceptions.HTTPError:
            raise UnknownBook(f"No metadata for {repr(name)}")

        if version is None:
            return meta.versions[-1].version

        # Verify that the version exists
        for item in meta.versions:
            if item.version == version:
                return version
        raise UnknownVersion(name, version)
