"""
Book

A Book represents a single versioned dataset. A dataset can contain multiple resources
each of which are loaded independently.
"""
import json
import os.path
import pathlib
from typing import Union
import datapackage
import pooch
import scmdata

from bookshelf.constants import DEFAULT_BOOKSHELF
from bookshelf.utils import build_url, create_local_cache, fetch_file


class _Book:
    def __init__(
        self,
        name: str,
        version: str,
        bookshelf: str = DEFAULT_BOOKSHELF,
    ):
        self.name = name
        self.version = version
        self.bookshelf = bookshelf

    def url(self, fname=None):
        parts = [self.name, self.version]
        if fname:
            parts.append(fname)
        build_url(self.bookshelf, *parts)

    def fetch(self):
        pass


class LocalBook(_Book):
    """
    A local instance of a Book

    This book may or may not have been deployed to a remote bookshelf
    """

    def __init__(
        self,
        name: str,
        version: str,
        local_bookshelf: Union[str, pathlib.Path, None] = None,
    ):
        super(LocalBook, self).__init__(name, version)

        if local_bookshelf is None:
            local_bookshelf = create_local_cache(local_bookshelf)
        self.local_bookshelf = pathlib.Path(local_bookshelf)
        self._metadata = None

    def local_fname(self, fname: str) -> str:
        """
        Get the name of a file in the package

        Parameters
        ----------
        fname : str
            Name of the file

        Returns
        -------
        str
            The filename for the file in the local bookshelf
        """
        return os.path.join(self.local_bookshelf, self.name, self.version, fname)

    def metadata(self) -> datapackage.Package:
        """
        Metadata about the current book

        :module:`datapackage` is used for handling the metadata.

        Returns
        -------
        :class:`datapackage.Package`
            Metadata about the Book
        """
        if self._metadata is None:
            fname = "datapackage.json"

            local_fname = self.local_fname(fname)
            with open(local_fname) as file_handle:
                d = json.load(file_handle)

            self._metadata = datapackage.Package(d)
        return self._metadata

    def add_timeseries(self, name, data):
        """
        Add a timeseries resource to the Book

        Updates the Books metadata

        Parameters
        ----------
        name : str
            Unique name of the resource
        data : scmdata.ScmRun
            Timeseries data to add to the Book
        """
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

    @classmethod
    def create_new(cls, name, version, **kwargs):
        """
        Create a new Book
        """
        book = LocalBook(name, version, **kwargs)
        book._metadata = datapackage.Package(
            {"name": name, "version": version, "resources": []}
        )
        book._metadata.save(book.local_fname("datapackage.json"))

        return book

    def timeseries(self, name: str) -> scmdata.ScmRun:
        """
        Get a timeseries resource

        If the data is not available in the local cache, it is downloaded from the
        remote BookShelf.

        Parameters
        ----------
        name : str
            Name of the volume

        Returns
        -------
            Timeseries data

        """
        resource: datapackage.Resource = self.metadata().get_resource(name)

        if resource is None:
            raise ValueError(f"Unknown timeseries '{resource}'")

        local_fname = self.local_fname(resource.descriptor["filename"])
        fetch_file(
            resource.descriptor.get("path"),
            pathlib.Path(local_fname),
            known_hash=resource.descriptor.get("hash"),
        )

        return scmdata.ScmRun(local_fname)
