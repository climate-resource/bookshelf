"""
Book

A Book represents a single versioned dataset. A dataset can contain multiple resources
each of which are loaded independently.
"""
import json
import os.path
import pathlib
import datapackage

import pooch
import scmdata

from bookshelf.constants import DEFAULT_BOOKSHELF
from bookshelf.utils import create_local_cache, build_url, fetch_file


class _Book:
    def __init__(
        self,
        name: str,
        version: str = None,
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


class RemoteBook(_Book):
    def fetch(self):
        pass


class LocalBook(_Book):
    """
    A local instance of a Book

    This book may or may not have been deployed to a remote bookshelf
    """

    def __init__(self, name, version, local_bookshelf: [str, pathlib.Path] = None):
        super(LocalBook, self).__init__(name, version)

        self.local_bookshelf = local_bookshelf
        if local_bookshelf is None:
            self.local_bookshelf = create_local_cache(local_bookshelf)
        self._metadata = None

    def local_fname(self, fname):
        return os.path.join(self.local_bookshelf, self.name, self.version, fname)

    def metadata(self) -> datapackage.Package:
        if self._metadata is None:
            fname = "datapackage.json"

            local_fname = self.local_fname(fname)
            with open(local_fname) as fh:
                d = json.load(fh)

            self._metadata = datapackage.Package(d)
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

    @classmethod
    def create_new(cls, name, version, **kwargs):
        book = LocalBook(name, version, **kwargs)
        book._metadata = datapackage.Package(
            {"name": name, "version": version, "resources": []}
        )
        book._metadata.save(book.local_fname("datapackage.json"))

        return book

    def timeseries(self, name) -> scmdata.ScmRun:
        resource: datapackage.Resource = self.metadata().get_resource(name)

        if resource is None:
            raise ValueError(f"Unknown timeseries '{resource}'")

        local_fname = self.local_fname(resource.descriptor["filename"])
        fetch_file(
            resource.descriptor.get("path"),
            local_fname,
            known_hash=resource.descriptor.get("hash"),
        )

        return scmdata.ScmRun(local_fname)
