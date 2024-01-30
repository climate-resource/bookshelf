"""
Schema
"""
import os
from typing import Any, Optional

import pooch
from pydantic import BaseModel, Field

from bookshelf.utils import get_env_var, get_notebook_directory

Version = str
Edition = int


class BookVersion(BaseModel):
    """
    Version information for a book
    """

    version: Version
    edition: Edition
    url: str
    hash: str
    private: Optional[bool] = False


class VolumeMeta(BaseModel):
    """
    Schema for a given Volume (A collection of Books with the same name)
    """

    name: str
    license: str  # A change in license will require a new volume
    versions: list[BookVersion]

    def get_latest_version(self) -> Version:
        """
        Get the latest version for a volume

        Returns
        -------
        Version string
        """
        ordered_versions = sorted([v.version for v in self.versions if not v.private])
        if not ordered_versions:
            raise ValueError("No published volumes")

        return ordered_versions[-1]

    def get_version(self, version: Version) -> list[BookVersion]:
        """
        Get a set of books for a given version

        Returns
        -------
        List of matching books sorted by edition
        """
        matching_versions = []

        for version_meta in self.versions:
            if version_meta.version == version:
                matching_versions.append(version_meta)

        matching_versions = sorted(matching_versions, key=lambda v: v.edition)
        return matching_versions


class FileDownloadInfo(BaseModel):
    """
    A File to be downloaded as part of a dataset
    """

    url: str
    """
    URL of the file to be downloaded

    This can be any URLs supported by :func:`pooch.download_file`, or a local file if the prefix "file://" is
    used. With local files, the filename must be a path relative to the notebooks directory. For example,
    `file://gdp-ndc-tool/13Mar2023a_CR_gdp_results.csv`.
    """
    hash: str
    """
    Hash of the file to be downloaded

    Used to verify the consistency of the downloaded file
    """


class ControlledVocabularyValue(BaseModel):
    """
    A value in a controlled vocabulary
    """

    value: str
    """
    Value of the controlled vocabulary
    """
    description: str
    """
    Description of the controlled vocabulary value
    """


class Dimension(BaseModel):
    """
    Dimension information

    A dimension describes a feature of the metadata (expressed as a column
    in the index of an {py:class}`scmdata.ScmRun`). This dimension can optionally be controlled by
    a controlled vocabulary which limits the possible values.
    """

    name: str
    """
    Name of the metadata dimension

    This is the same as the column in {py:class}`scmdata.ScmRun`
    """
    description: str
    """
    Description of the metadata dimension
    """
    type: str
    """
    Type of the values in the metadata dimension

    This is not currently verified
    """
    required_column: bool = Field(default=True)
    """
    Indication about whether this metadata dimension is compulsory in all the dataset in the book
    """
    allowed_NA: bool
    """
    Indication about whether all values in this metadata dimension must be non-empty
    """
    controlled_vocabulary: Optional[list[ControlledVocabularyValue]] = None
    """
    List of possible controlled vocabulary of this metadata dimension
    """


class DatasetMetadata(BaseModel):
    """
    Metadata about a dataset

    A dataset may consist of multiple files (:class:`FileDownloadInfo`)
    """

    url: Optional[str]
    doi: Optional[str]
    files: list[FileDownloadInfo] = Field(default_factory=list)
    author: str


class VersionMetadata(BaseModel):
    """
    Metadata about a single version of a book
    """

    version: Version
    dataset: DatasetMetadata
    private: Optional[bool] = Field(default=False)


class NotebookMetadata(BaseModel):
    """
    Schema for a running a notebook

    This represents the metadata for a selected version of a volume
    """

    name: str
    version: Version
    edition: Edition
    description: Optional[str]
    license: str
    source_file: str
    private: bool
    metadata: dict[str, Any]  # TODO: type this
    dataset: DatasetMetadata
    data_dictionary: list[Dimension] = Field(default_factory=list)

    def long_name(self) -> str:
        """
        Long name of the book

        Includes name and long version

        Returns
        -------
        str
            Long identifier for a book
        """
        return f"{self.name}@{self.long_version()}"

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

    def download_file(self, idx: int = 0) -> str:
        """
        Download a dataset file

        Uses ``pooch`` to manage the downloading, verification and caching of data file.
        The first call will trigger a download and subsequent calls may use the cached
        file if the previous download succeeded.

        Parameters
        ----------
        idx
            Index of the file to download (0-based). Defaults to the first file if
            no value is provided

        Returns
        -------
        str
            Filename of the locally downloaded file
        """
        cache_location = get_env_var("DOWNLOAD_CACHE_LOCATION", raise_on_missing=False, default=None)

        try:
            file_info = self.dataset.files[idx]
        except IndexError as e:
            raise ValueError("Requested index does not exist") from e

        file_hash: Optional[str] = file_info.hash
        if not file_hash:
            # replace an empty string with None
            file_hash = None

        if file_info.url.startswith("file://"):
            return os.path.join(get_notebook_directory(), file_info.url[7:])

        res: str = pooch.retrieve(
            file_info.url,
            known_hash=file_hash,
            path=cache_location,
        )
        return res


class ConfigSchema(BaseModel):
    """
    Schema for a given Volume (A collection of Books with the same name)

    A volume can hold multiple versions of the same data
    """

    name: str
    edition: Edition
    description: Optional[str]
    license: str
    source_file: str
    metadata: dict[str, Any]  # TODO: type this
    versions: list[VersionMetadata]
    data_dictionary: list[Dimension] = Field(default_factory=list)
