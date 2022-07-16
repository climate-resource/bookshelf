"""
Book


"""
import json
import os.path
import pathlib
import datapackage

import pooch
import scmdata

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


def _fetch_file(url, local_fname, known_hash=None, force=False):
    existing_hash = None
    if os.path.exists(local_fname):
        if pooch.hashes.hash_matches(local_fname, known_hash):
            return
        else:
            raise ValueError(
                f"Hash for existing file {local_fname} does not match the expected value {known_hash}"
            )

    if force or existing_hash is None:
        download(url, local_fname=local_fname, known_hash=known_hash)

    current_hash = None
    if existing_hash and existing_hash != current_hash:
        # The package metadata has been updated
        pass

    if not os.path.exists(local_fname):
        raise FileNotFoundError(f"Could not find file {local_fname}")


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

    local_fname = pathlib.Path(local_bookshelf) / name / fname
    url = build_url(remote_bookshelf, name, fname)

    _fetch_file(url, local_fname)

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
    url = build_url(remote_bookshelf, name, version, fname)

    _fetch_file(url, local_fname)

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
        self._version = version
        self.bookshelf = bookshelf
        self.local_bookshelf = local_bookshelf
        if local_bookshelf is None:
            self.local_bookshelf = create_local_cache(local_bookshelf)
        self._metadata = None

    @classmethod
    def create_new(cls, name, version, **kwargs):
        book = Book(name, version, **kwargs)
        book._metadata = datapackage.Package(
            {"name": name, "version": version, "resources": []}
        )
        book._metadata.save(book.local_fname("datapackage.json"))

        return book

    @property
    def version(self):
        if self._version is None:
            self._version = self._resolve_version(self._version)
        return self._version

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

    def url(self, fname=None):
        parts = [self.name, self.version]
        if fname:
            parts.append(fname)
        build_url(self.bookshelf, *parts)

    def local_fname(self, fname):
        return os.path.join(self.local_bookshelf, self.name, self.version, fname)

    def fetch(self, known_hash=None, progressbar=False):
        package = _fetch_book(
            self.name,
            self.version,
            remote_bookshelf=self.bookshelf,
            local_bookshelf=self.local_bookshelf,
        )

    def metadata(self) -> datapackage.Package:
        if self._metadata is None:
            # Fetch the existing data if it exists
            self._metadata = _fetch_book(
                self.name,
                self.version,
                remote_bookshelf=self.bookshelf,
                local_bookshelf=self.local_bookshelf,
            )

        return self._metadata

    def add_timeseries(self, name, data):
        fname = f"{name}.csv"
        data.to_csv(self.local_fname(fname))
        hash = pooch.hashes.file_hash(self.local_fname(fname))

        self.metadata().add_resource(
            {
                "name": name,
                "format": "CSV",
                "filename": fname,
                "hash": hash,
            }
        )
        self.metadata().save(self.local_fname("datapackage.json"))

    def timeseries(self, name) -> scmdata.ScmRun:
        resource: datapackage.Resource = self.metadata().get_resource(name)

        if resource is None:
            raise ValueError(f"Unknown timeseries '{resource}'")

        local_fname = self.local_fname(resource.descriptor["filename"])
        _fetch_file(
            resource.descriptor.get("path"),
            local_fname,
            known_hash=resource.descriptor.get("hash"),
        )

        return scmdata.ScmRun(local_fname)
