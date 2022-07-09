"""
Book


"""
import json
import os.path
import pathlib
import datapackage

import pooch
from bookshelf.constants import DEFAULT_BOOKSHELF
from bookshelf.utils import create_local_cache, download, build_url
from bookshelf.schema import VolumeMeta


def fetch(name: str, version: str = None):
    """
    Fetch a package

    Fetches a package from the remote bookshelf if it isn't already available
    in a local bookshelf.

    Parameters
    ----------
    name : str
        Name of the book

    version : str
        Version of the book to fetch

        If not provided the latest version will be fetched

    Returns
    -------
    Book

    """
    book = Book(name, version=version)

    return book.fetch()


def _fetch_volume_meta(
    name: str,
    remote_bookshelf: [str, pathlib.Path],
    local_bookshelf: [str, pathlib.Path],
    fetch=True,
) -> VolumeMeta:
    """
    Fetch information about the books available for a given volume

    Parameters
    ----------
    name : str
        Name of the volume to fetch
    remote_bookshelf : str
        URL for the remote bookshelf
    local_bookshelf : str
        Local path where downloaded books will be stored.

        Must be a writable directory
    fetch: bool
        If True metadata is always fetched from the remote bookshelf

    Returns
    -------
    VolumeMeta
    """

    fname = "volume.json"

    local_fname = pathlib.Path(local_bookshelf) / name

    existing_hash = None
    if os.path.exists(local_fname):
        pass

    # TODO: catch errors
    url = build_url(remote_bookshelf, name, fname)
    if fetch:
        download(url, local_fname=local_fname, known_hash=None)

        current_hash = None
        if existing_hash and existing_hash != current_hash:
            # The package metadata has been updated
            pass

    if not os.path.exists(local_fname):
        raise FileNotFoundError(f"Could not find file {local_fname}")

    with open(local_fname) as fh:
        d = json.load(fh)

    return VolumeMeta(**d)


def _fetch_book(
    name: str,
    version: str,
    remote_bookshelf: [str, pathlib.Path],
    local_bookshelf: [str, pathlib.Path],
    fetch=True,
) -> datapackage.Package:
    """
    Fetch a book from the remote bookshelf

    Parameters
    ----------
    name : str
        Name of the volume to fetch
    version : str
        Version to fetch
    remote_bookshelf : str
        URL for the remote bookshelf
    local_bookshelf : str
        Local path where downloaded books will be stored.

        Must be a writable directory
    fetch: bool
        If True metadata is always fetched from the remote bookshelf

    Raises
    ------
    bookshelf.errors.FetchError
        If a corresponding book does not exist


    Returns
    -------
    # TODO: perhaps this should return a class that contains the datapackage to
    be consistent with VolumeMeta
    datapackage.Package
    """

    fname = "datapackage.json"

    local_fname = pathlib.Path(local_bookshelf) / name / version / fname

    existing_hash = None
    if os.path.exists(local_fname):
        pass

    # TODO: catch errors
    url = build_url(remote_bookshelf, name, version, fname)
    if fetch:
        download(url, local_fname=local_fname, known_hash=None)

        current_hash = None
        if existing_hash and existing_hash != current_hash:
            # The package metadata has been updated
            pass

    if not os.path.exists(local_fname):
        raise FileNotFoundError(f"Could not find file {local_fname}")

    with open(local_fname) as fh:
        d = json.load(fh)

    return datapackage.Package(d)


class Book:
    def __init__(
        self,
        name: str,
        version: str = None,
        bookshelf: str = DEFAULT_BOOKSHELF,
        local_bookshelf=None,
    ):
        self.name = name
        self.version = version
        self.bookshelf = bookshelf
        self.local_bookshelf = create_local_cache(local_bookshelf)

    def _resolve_version(self, version):
        # Update the package metadata
        meta = _fetch_volume_meta(self.name, self.bookshelf, self.local_bookshelf)

        if version is None:
            return meta.versions[-1].version
        else:
            # Verify that the version exists
            for v in meta.versions:
                if v.version == version:
                    return version
            raise ValueError(f"Version {version} does not exist")

    @property
    def url(self):
        if self.version is None:
            self.version = self._resolve_version(self.version)
        return f"{self.bookshelf}/{self.name}/{self.version}"

    def fetch(self, known_hash=None, progressbar=False):
        if self.version is None:
            self.version = self._resolve_version(self.version)
        package = _fetch_book(
            self.name,
            self.version,
            remote_bookshelf=self.bookshelf,
            local_bookshelf=self.local_bookshelf,
        )

        pass
