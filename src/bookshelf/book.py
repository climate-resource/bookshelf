"""
Books

A Book represents a single versioned dataset. A dataset can contain multiple resources
each of which are loaded independently.
"""
import glob
import json
import os.path
import pathlib
from collections.abc import Iterable
from typing import Any, Optional, Union, cast

import datapackage
import pooch
import scmdata

from bookshelf.schema import Edition, NotebookMetadata, Version
from bookshelf.utils import (
    build_url,
    create_local_cache,
    fetch_file,
    get_remote_bookshelf,
)

DATAPACKAGE_FILENAME = "datapackage.json"


class _Book:
    def __init__(
        self,
        name: str,
        version: str,
        edition: int,
        bookshelf: Optional[str] = None,
    ):
        self.name = name
        self.version = version
        self.edition = edition
        self.bookshelf = get_remote_bookshelf(bookshelf)

    def long_version(self) -> str:
        """
        Long version identifier

        Of the form "{version}_e{edition}" e.g. v1.0.1_e002.

        Returns
        -------
        str
            Version identification string
        """
        return f"{self.version}_e{self.edition:03}"

    @staticmethod
    def path_parts(
        name: str,
        version: Version,
        edition: Edition,
        fname: Optional[str] = None,
    ) -> Iterable[str]:
        """
        Build the parts needed to unambiguously reference an edition.

        Parameters
        ----------
        name
            Book name
        version
            Book version
        edition
            Book edition
        fname
            If provided, reference a specific file within the data
        Returns
        -------
            Iterable of the parts, which can be joined as needed to get
            a path.
        """
        parts = [name, f"{version}_e{edition:03}"]
        if fname is not None:
            parts.append(fname)
        return parts

    @classmethod
    def relative_path(
        cls,
        name: str,
        version: Version,
        edition: Edition,
        fname: Optional[str] = None,
    ) -> str:
        """
        Build the relative path of the edition

        Parameters
        ----------
        name
            Book name
        version
            Book version
        edition
            Book edition
        fname
            If provided, reference a specific file within the data
        Returns
        -------
            Relative path to the book or resource within the book
        """
        return os.path.join(
            *cls.path_parts(name=name, version=version, edition=edition, fname=fname)
        )

    def url(self, fname: Optional[str] = None) -> str:
        """
        Get the expected URL for the book

        This URL is generated locally using the provided remote bookshelf

        Parameters
        ----------
        fname : str
            If provided get the URL of a file within the Book

        Returns
        -------
        str
            URL
        """
        return build_url(
            self.bookshelf,
            *self.path_parts(self.name, self.version, self.edition, fname),
        )


class LocalBook(_Book):
    """
    A local instance of a Book

    A Book consists of a metadata file (``datapackage.json``) and one or more ``Resource`` files.
    For now, these ``Resource's`` are only csv files of timeseries in the IAMC format, but
    this could be extended in future to handle additional data-types. Resources are fetched from
    the remote bookshelf when first requested and are cached locally for subsequent use.

    The ``Book`` metadata follow the ``datapackage`` specification with some additional metadata
    specific to this project. That means that each ``Book`` also doubles as a ``datapackage``.
    Once released by the ``Book`` author, a ``Book`` becomes immutable. If ``Book`` authors
    wish to update the metadata or data contained within a ``Book`` they must upload a new
    version of the ``Book``.
    """

    def __init__(
        self,
        name: str,
        version: str,
        edition: int = 1,
        local_bookshelf: Union[str, pathlib.Path, None] = None,
    ):
        super().__init__(name, version, edition)

        if local_bookshelf is None:
            local_bookshelf = create_local_cache(local_bookshelf)
        self.local_bookshelf = pathlib.Path(local_bookshelf)
        self._metadata: Optional[datapackage.Package] = None

    def hash(self) -> str:
        """
        Get the hash for the metadata

        This effectively also hashes the data as the metadata contains the hashes of
        the local Resource files.

        Returns
        -------
        str
            sha256 sum that is unique for the Book
        """
        return str(pooch.file_hash(self.local_fname(DATAPACKAGE_FILENAME)))

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
        return os.path.join(self.local_bookshelf, self.name, self.long_version(), fname)

    def as_datapackage(self) -> datapackage.Package:
        """
        Datapackage for the current book

        :mod:`datapackage` is used for handling the metadata. Modifying
        the package also modifies the Book.

        Returns
        -------
        :class:`datapackage.Package`
            Metadata about the Book
        """
        if self._metadata is None:
            fname = DATAPACKAGE_FILENAME

            local_fname = self.local_fname(fname)
            with open(local_fname) as file_handle:
                file_data = json.load(file_handle)

            self._metadata = datapackage.Package(file_data)
        return self._metadata

    def metadata(self) -> dict[str, Any]:
        """
        Metadata about the current book

        Returns
        -------
        dict
            Metadata about the Book
        """
        return cast(dict[str, Any], self.as_datapackage().descriptor)

    def files(self) -> list[str]:
        """
        List of files that are locally available

        Since each Resource is fetched when first read the number of files present may
        be less than available on the remote bookshelf.

        Returns
        -------
        list of str
            List of paths of all Book's files, including `datapackage.json` which contains
            the metadata about the Book.
        """
        file_list = glob.glob(self.local_fname("*"))
        return file_list

    def add_timeseries(self, name: str, data: scmdata.ScmRun) -> None:
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

        # TODO: this flag could be exposed in future
        quoting = None  # csv.QUOTE_NONNUMERIC
        data.timeseries().sort_index().to_csv(self.local_fname(fname), quoting=quoting)
        resource_hash = pooch.hashes.file_hash(self.local_fname(fname))

        metadata = self.as_datapackage()
        metadata.add_resource(
            {
                "name": name,
                "format": "CSV",
                "filename": fname,
                "hash": resource_hash,
            }
        )
        metadata.save(self.local_fname(DATAPACKAGE_FILENAME))

    @classmethod
    def create_new(
        cls, name: str, version: Version, edition: Edition = 1, **kwargs: Any
    ) -> "LocalBook":
        """
        Create a new Book
        """
        book = LocalBook(name, version, edition, **kwargs)
        book._metadata = datapackage.Package(
            {"name": name, "version": version, "edition": edition, "resources": []}
        )
        book._metadata.save(book.local_fname(DATAPACKAGE_FILENAME))

        return book

    @classmethod
    def create_from_metadata(cls, meta: NotebookMetadata, **kwargs: str) -> "LocalBook":
        """
        Create a new book from a notebook

        Parameters
        ----------
        meta : NotebookMetadata
            Metadata about the book

        kwargs
            Additional arguments passed to :class:`LocalBook`

        Returns
        -------
        LocalBook
            An instance of a local book with the datapackage setup
        """
        book = LocalBook(meta.name, version=meta.version, edition=meta.edition, **kwargs)
        book._metadata = datapackage.Package(
            {
                "name": meta.name,
                "version": meta.version,
                "private": meta.private,
                "edition": meta.edition,
                "resources": [],
            }
        )
        book._metadata.save(book.local_fname(DATAPACKAGE_FILENAME))

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
        resource: datapackage.Resource = self.as_datapackage().get_resource(name)

        if resource is None:
            raise ValueError(f"Unknown timeseries '{name}'")

        local_fname = self.local_fname(resource.descriptor["filename"])
        fetch_file(
            self.url(resource.descriptor.get("filename")),
            pathlib.Path(local_fname),
            known_hash=resource.descriptor.get("hash"),
        )

        return scmdata.ScmRun(local_fname)
