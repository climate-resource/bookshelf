"""
Schema
"""
from typing import Any, Dict, List, Optional

import pooch
from pydantic import BaseModel  # pylint: disable=no-name-in-module

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


class VolumeMeta(BaseModel):
    """
    Schema for a given Volume (A collection of Books with the same name)
    """

    name: str
    license: str  # A change in license will require a new volume
    versions: List[BookVersion]

    def get_latest_version(self) -> Version:
        """
        Get the latest version for a volume

        Returns
        -------
        Version string
        """
        ordered_versions = sorted([v.version for v in self.versions])
        if not len(ordered_versions):
            raise ValueError("No published volumes")

        return ordered_versions[-1]

    def get_version(self, version: Version) -> List[BookVersion]:
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
    url: str
    hash: str


class DatasetMetadata(BaseModel):
    url: Optional[str]
    doi: Optional[str]
    files: List[FileDownloadInfo]
    author: str


class VersionMetadata(BaseModel):
    version: Version
    dataset: DatasetMetadata


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
    metadata: Dict[str, Any]  # TODO: type this
    dataset: Optional[DatasetMetadata]

    def long_name(self):
        return f"{self.name}@{self.long_version()}"

    def long_version(self):
        return f"{self.version}_e{self.edition:03}"

    def download_file(self, idx: int = 0) -> str:
        file_info = self.dataset.files[idx]

        hash = file_info.hash
        if not hash:
            hash = None
        return pooch.retrieve(
            file_info.url,
            known_hash=hash,
        )


class ConfigSchema(BaseModel):
    """
    Schema for a given Volume (A collection of Books with the same name)

    A volume can hold multiple versions of the same data (
    """

    name: str
    edition: Edition
    description: Optional[str]
    license: str
    source_file: str
    metadata: Dict[str, Any]  # TODO: type this
    versions: List[VersionMetadata]
