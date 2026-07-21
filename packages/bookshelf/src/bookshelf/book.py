"""
A Book represents a single versioned dataset.

A dataset can contain multiple resources each of which are loaded independently.
"""

import glob
import hashlib
import json
import os.path
import pathlib
from collections.abc import Iterable
from typing import Any, cast

import datapackage
import pandas as pd
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
        bookshelf: str | None = None,
    ):
        self.name = name
        self.version = version
        self.edition = edition
        self.bookshelf = get_remote_bookshelf(bookshelf)

    def long_version(self) -> str:
        """
        Long version identifier

        Of the form `{version}_e{edition}` e.g. "v1.0.1_e002".

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
        fname: str | None = None,
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
        fname: str | None = None,
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
        return os.path.join(*cls.path_parts(name=name, version=version, edition=edition, fname=fname))

    def url(self, fname: str | None = None) -> str:
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

    A Book consists of a metadata file (`datapackage.json`) and one or more `Resource` files.
    For now, these `Resource's` are only csv files of timeseries in the IAMC format, but
    this could be extended in future to handle additional data-types. Resources are fetched from
    the remote bookshelf when first requested and are cached locally for subsequent use.

    The `Book` metadata follow the `datapackage` specification with some additional metadata
    specific to this project. That means that each `Book` also doubles as a `datapackage`.
    Once released by the `Book` author, a `Book` becomes immutable. If `Book` authors
    wish to update the metadata or data contained within a `Book` they must upload a new
    version of the `Book`.
    """

    def __init__(
        self,
        name: str,
        version: str,
        edition: int = 1,
        local_bookshelf: str | pathlib.Path | None = None,
    ):
        super().__init__(name, version, edition)

        if local_bookshelf is None:
            local_bookshelf = create_local_cache(local_bookshelf)
        self.local_bookshelf = pathlib.Path(local_bookshelf)
        self._metadata: datapackage.Package | None = None

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
        :
            The filename for the file in the local bookshelf
        """
        return os.path.join(self.local_bookshelf, self.name, self.long_version(), fname)

    def as_datapackage(self) -> datapackage.Package:
        """
        Datapackage for the current book

        `datapackage` is used for handling the metadata. Modifying
        the package also modifies the Book.

        Returns
        -------
        `datapackage.Package`
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
        :
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
        :
            List of paths of all Book's files, including `datapackage.json` which contains
            the metadata about the Book.
        """
        file_list = glob.glob(self.local_fname("*"))
        return file_list

    def add_timeseries(
        self, timeseries_name: str, data: scmdata.ScmRun, compressed: bool = True, write_long: bool = True
    ) -> None:
        """
        Add two timeseries resource (wide format and long format) to the Book

        Updates the Books metadata

        Parameters
        ----------
        timeseries_name : str
            Name of the resource
        data : scmdata.ScmRun
            Timeseries data to add to the Book
        compressed: bool
            Whether compressed the file or not
        write_long: bool
            Whether to write the long format timeseries data or not
        """
        if compressed:
            compression_info = {"format": "csv.gz", "compression": "gzip"}
        else:
            compression_info = {"format": "csv", "compression": "infer"}

        self.write_wide_timeseries(data, timeseries_name, compression_info)
        if write_long:
            self.write_long_timeseries(data, timeseries_name, compression_info)

    def write_wide_timeseries(
        self, data: scmdata.ScmRun, timeseries_name: str, compression_info: dict[str, str]
    ) -> None:
        """
        Add the wide format timeseries data to the Book

        Parameters
        ----------
        data : scmdata.ScmRun
            Timeseries data to add to the Book
        timeseries_name: str
            Name of the resource
        compression_info: dict
            A dictionary about the format of the file and the compression type
        """
        shape = "wide"
        metadata = self.as_datapackage()

        name = get_resource_key(timeseries_name=timeseries_name, shape=shape)
        fname = get_resource_filename(
            book_name=self.name,
            long_version=self.long_version(),
            timeseries_name=timeseries_name,
            shape=shape,
            file_format=compression_info["format"],
        )

        timeseries_data = pd.DataFrame(data.timeseries().sort_index())

        timeseries_data.to_csv(  # type: ignore
            path_or_buf=self.local_fname(fname),
            compression=compression_info["compression"],
        )
        resource_hash = pooch.hashes.file_hash(self.local_fname(fname))
        content_hash = hashlib.sha256(timeseries_data.to_csv().encode()).hexdigest()
        metadata.add_resource(
            {
                "name": name,
                "timeseries_name": timeseries_name,
                "shape": shape,
                "format": compression_info["format"],
                "filename": fname,
                "hash": resource_hash,
                "content_hash": content_hash,
            }
        )
        metadata.save(self.local_fname(DATAPACKAGE_FILENAME))

    def write_long_timeseries(
        self, data: scmdata.ScmRun, timeseries_name: str, compression_info: dict[str, str]
    ) -> None:
        """
        Add the long format timeseries data to the Book

        Parameters
        ----------
        data : scmdata.ScmRun
            Timeseries data to add to the Book
        timeseries_name: str
            Name of the resource
        compression_info: dict
            A dictionary about the format of the file and the compression type
        """

        def chunked_melt(
            data: pd.DataFrame, id_vars: list[str], var_name: str, value_name: str
        ) -> pd.DataFrame:
            """
            Melt wide format timeseries data to long format

            Efficiently melts large wide-format timeseries data into long format in chunks,
            addressing performance and memory issues associated with melting large DataFrames.

            Parameters
            ----------
            data : pd.DataFrame
                The wide-format DataFrame to be melted into long format.
            id_vars : list[str]
                Column(s) to use as identifier variables. These columns will be
                preserved during the melt operation.
            var_name : str
                Name to assign to the variable column in the melted DataFrame.
            value_name : str
                Name to assign to the value column in the melted DataFrame.
                This name must not match any existing column labels in `data`.

            Returns
            -------
            pd.DataFrame
                The melted DataFrame in long format, combining all chunks.
            """
            pivot_list = list()
            chunk_size = 100000

            for i in range(0, len(data), chunk_size):
                row_pivot = data.iloc[i : i + chunk_size].melt(
                    id_vars=id_vars, var_name=var_name, value_name=value_name
                )
                pivot_list.append(row_pivot)

            melt_df = pd.concat(pivot_list)
            return melt_df

        shape = "long"
        metadata = self.as_datapackage()

        name = get_resource_key(timeseries_name=timeseries_name, shape=shape)
        fname = get_resource_filename(
            book_name=self.name,
            long_version=self.long_version(),
            timeseries_name=timeseries_name,
            shape=shape,
            file_format=compression_info["format"],
        )

        var_lst = list(data.meta.columns)
        sort_lst = [*var_lst, "year"]
        data_df = pd.DataFrame(data.timeseries().sort_index().reset_index())
        data_melt = chunked_melt(data_df, var_lst, "year", "values").sort_values(by=sort_lst)
        data_melt.to_csv(  # type: ignore
            path_or_buf=self.local_fname(fname),
            sep=",",
            index=False,
            header=True,
            compression=compression_info["compression"],
        )
        resource_hash = pooch.hashes.file_hash(self.local_fname(fname))
        content_hash = hashlib.sha256(data_melt.to_csv().encode()).hexdigest()
        metadata.add_resource(
            {
                "name": name,
                "timeseries_name": timeseries_name,
                "shape": shape,
                "format": compression_info["format"],
                "filename": fname,
                "hash": resource_hash,
                "content_hash": content_hash,
            }
        )
        metadata.save(self.local_fname(DATAPACKAGE_FILENAME))

    @classmethod
    def create_new(cls, name: str, version: Version, edition: Edition = 1, **kwargs: Any) -> "LocalBook":
        """
        Create a new Book for a given name, version and edition

        Returns
        -------
        :
            An instance of a local book
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
        :
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

    def timeseries(self, timeseries_name: str) -> scmdata.ScmRun:
        """
        Get a timeseries resource

        If the data is not available in the local cache, it is downloaded from the
        remote BookShelf.

        Parameters
        ----------
        timeseries_name : str
            Name of the resource

        Returns
        -------
        :
            Timeseries data

        """
        timeseries_shape = "wide"
        key_name = get_resource_key(timeseries_name=timeseries_name, shape=timeseries_shape)
        resource: datapackage.Resource = self.as_datapackage().get_resource(key_name)
        if resource is None:
            raise ValueError(f"Unknown timeseries '{key_name}'")
        local_fname = self.local_fname(resource.descriptor["filename"])
        fetch_file(
            self.url(resource.descriptor.get("filename")),
            pathlib.Path(local_fname),
            known_hash=resource.descriptor.get("hash"),
        )

        return scmdata.ScmRun(local_fname)

    def get_long_format_data(self, timeseries_name: str) -> pd.DataFrame:
        """
        Get a timeseries resource in long format

        If the data is not available in the local cache, it is downloaded from the
        remote BookShelf.

        Parameters
        ----------
        timeseries_name : str
            Name of the volume

        Returns
        -------
        :
            Timeseries data

        """
        timeseries_shape = "long"
        key_name = get_resource_key(timeseries_name=timeseries_name, shape=timeseries_shape)
        resource: datapackage.Resource = self.as_datapackage().get_resource(key_name)
        if resource is None:
            raise ValueError(f"Unknown timeseries '{key_name}'")
        local_fname = self.local_fname(resource.descriptor["filename"])
        fetch_file(
            self.url(resource.descriptor.get("filename")),
            pathlib.Path(local_fname),
            known_hash=resource.descriptor.get("hash"),
        )
        return pd.read_csv(local_fname)


def get_resource_key(*, timeseries_name: str, shape: str) -> str:
    """
    Construct a resource key name by concatenating all given arguments with underscores.

    Take any number of string arguments, concatenate them using an underscore as a separator,
    and return the resulting string.

    Parameters
    ----------
    timeseries_name : str
        The name of the timeseries the resource represents.
    shape : str
        The shape of the data (e.g., 'wide', 'long') the resource contains.

    Returns
    -------
    :
        The concatenated key name formed from all the input arguments.
    """
    key_name_tuple = (timeseries_name, shape)
    key_name = "_".join(key_name_tuple)
    return key_name


def get_resource_filename(
    *, book_name: str, long_version: str, timeseries_name: str, shape: str, file_format: str
) -> str:
    """
    Generate a resource filename using specified attributes and file format.

    This function constructs a filename by concatenating given book attributes with underscores
    and appending the specified file format.

    Parameters
    ----------
    book_name : str
        The name of the book the resource is associated with.
    long_version : str
        The long version identifier for the resource.
    timeseries_name : str
        The name of the timeseries the resource represents.
    shape : str
        The shape of the data (e.g., 'wide', 'long') the resource contains.
    file_format : str
        The file format extension (without the period) for the resource file (e.g., 'csv', 'csv.gz').

    Returns
    -------
    :
        The constructed filename in the format
        `{book_name}_{long_version}_{timeseries_name}_{shape}.{file_format}`.
    """
    filename_tuple = (book_name, long_version, timeseries_name, shape)
    filename = "_".join(filename_tuple)
    return f"{filename}.{file_format}"
