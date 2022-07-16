"""
BookShelf

A BookShelf is a collection of Books
"""

import json
import os
import pathlib

import requests.exceptions

from bookshelf.book import LocalBook
from bookshelf.constants import DEFAULT_BOOKSHELF
from bookshelf.errors import UnknownBook, UnknownVersion
from bookshelf.schema import VolumeMeta
from bookshelf.utils import build_url, create_local_cache, fetch_file


def _fetch_volume_meta(
    name: str,
    remote_bookshelf: str,
    local_bookshelf: pathlib.Path,
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
    local_bookshelf : pathlib.Path
        Local path where downloaded books will be stored.

        Must be a writable directory
    fetch: bool
        If True metadata is always fetched from the remote bookshelf

    Returns
    -------
    VolumeMeta
    """

    fname = "volume.json"

    local_fname = local_bookshelf / name / fname
    url = build_url(remote_bookshelf, name, fname)

    fetch_file(url, local_fname)

    with open(str(local_fname)) as fh:
        d = json.load(fh)

    return VolumeMeta(**d)


class BookShelf:
    def __init__(
        self,
        path: [str, pathlib.Path] = None,
        remote_bookshelf: str = DEFAULT_BOOKSHELF,
    ):
        if path is None:
            path = create_local_cache(path)
        self.path = pathlib.Path(path)
        self.remote_bookshelf = remote_bookshelf

    def load(self, name: str, version: str = None) -> LocalBook:
        """
        Load a book

        If the book's metadata does not exist locally or an unknown version is requested
        the remote bookshelf is queried, otherwise the local metadata is used.

        """
        if version is None:
            version = self._resolve_version(name, version)

        metadata_fragment = os.path.join(name, version, "datapackage.json")
        metadata_fname = self.path / metadata_fragment

        if not metadata_fname.exists():
            try:
                url = build_url(self.remote_bookshelf, metadata_fragment)
                fetch_file(url, local_fname=metadata_fname, known_hash=None)
            except requests.exceptions.HTTPError:
                raise UnknownVersion(f"Could not find {name}@{version}")
        assert metadata_fname.exists()

        return LocalBook(name, version, local_bookshelf=self.path)

    def save(self, book: LocalBook):
        raise NotImplementedError

    def _resolve_version(self, name, version) -> str:
        # Update the package metadata
        try:
            meta = _fetch_volume_meta(name, self.remote_bookshelf, self.path)
        except requests.exceptions.HTTPError:
            raise UnknownBook(f"No metadata for {repr(name)}")

        if version is None:
            return meta.versions[-1].version
        else:
            # Verify that the version exists
            for v in meta.versions:
                if v.version == version:
                    return version
            raise ValueError(f"Version {version} does not exist")
