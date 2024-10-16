"""
A BookShelf is a collection of Books that can be queried and fetched as needed.
"""

import json
import logging
import pathlib

import requests.exceptions

from bookshelf.book import LocalBook
from bookshelf.errors import UnknownBook, UnknownEdition, UnknownVersion
from bookshelf.schema import Edition, Version, VolumeMeta
from bookshelf.utils import (
    build_url,
    create_local_cache,
    fetch_file,
    get_remote_bookshelf,
)

logger = logging.getLogger(__name__)


def fetch_volume_meta(
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


class BookShelf:
    """
    A BookShelf stores a number of Books

    If a Book isn't available locally, it will be queried from the remote bookshelf.

    Books can be fetched using [load][bookshelf.BookShelf.load] by name.
    Specific versions of a book can be pinned if needed,
    otherwise the latest version of the book is loaded.
    """

    def __init__(
        self,
        path: str | pathlib.Path | None = None,
        remote_bookshelf: str | None = None,
    ):
        if path is None:
            path = create_local_cache(path)
        self.path = pathlib.Path(path)
        self.remote_bookshelf = get_remote_bookshelf(remote_bookshelf)

    def load(
        self,
        name: str,
        version: Version | None = None,
        edition: Edition | None = None,
        force: bool = False,
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
        edition: int
            Edition of book to load

            If no edition is provided, the latest edition of the selected version is returned
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
        if version is None or edition is None or force:
            version, edition = self._resolve_version(name, version, edition)
        metadata_fragment = LocalBook.relative_path(name, version, edition, "datapackage.json")
        metadata_fname = self.path / metadata_fragment
        if not metadata_fname.exists():
            try:
                url = build_url(
                    self.remote_bookshelf,
                    *LocalBook.path_parts(name, version, edition, "datapackage.json"),
                )
                fetch_file(
                    url,
                    local_fname=metadata_fname,
                    known_hash=None,
                    force=force,
                )
            except requests.exceptions.HTTPError as http_error:
                raise UnknownVersion(name, version) from http_error

        if not metadata_fname.exists():
            raise AssertionError()
        return LocalBook(name, version, edition, local_bookshelf=self.path)

    def is_available(
        self,
        name: str,
        version: Version | None = None,
        edition: Edition | None = None,
    ) -> bool:
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
            self._resolve_version(name, version, edition)
        except (UnknownBook, UnknownVersion, UnknownEdition):
            return False
        return True

    def is_cached(self, name: str, version: Version, edition: Edition) -> bool:
        """
        Check if a book with a matching name/version is cached on the local bookshelf

        Parameters
        ----------
        name : str
            Name of the volume to check
        version : str
            Version of the volume to check
        edition : int
            Edition of the volume to check

        Returns
        -------
        bool
            True if a matching book is cached locally
        """
        try:
            # Check if the metadata for the book can be successfully read
            book = LocalBook(name, version, edition, local_bookshelf=self.path)
            book.metadata()
        except FileNotFoundError:
            return False
        return True

    def _resolve_version(
        self,
        name: str,
        version: Version | None = None,
        edition: Edition | None = None,
    ) -> tuple[Version, Edition]:
        # Update the package metadata
        try:
            meta = fetch_volume_meta(name, self.remote_bookshelf, self.path)
        except requests.exceptions.HTTPError as http_error:
            raise UnknownBook(f"No metadata for {name!r}") from http_error

        if version is None:
            version = meta.get_latest_version()

        # Verify that the version exists
        matching_version_books = meta.get_version(version)
        if not matching_version_books:
            raise UnknownVersion(name, version)

        # Find edition
        if edition is None:
            edition = matching_version_books[-1].edition
        if edition not in [b.edition for b in matching_version_books]:
            raise UnknownEdition(name, version, edition)
        return version, edition

    def list_versions(self, name: str) -> list[str]:
        """
        Get a list of available versions for a given Book

        Parameters
        ----------
        name: str
            Name of book

        Returns
        -------
        list of str
            List of available versions
        """
        try:
            meta = fetch_volume_meta(name, self.remote_bookshelf, self.path)
        except requests.exceptions.HTTPError as http_error:
            raise UnknownBook(f"No metadata for {name!r}") from http_error

        return [version.version for version in meta.versions if not version.private]

    def list_books(self) -> list[str]:
        """
        Get a list of book names

        Returns
        -------
        list of str
            List of available books
        """
        raise NotImplementedError
