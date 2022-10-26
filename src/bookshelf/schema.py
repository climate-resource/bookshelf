"""
Schema
"""
from typing import Any, Dict, List, Optional

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


class NotebookMetadata(BaseModel):
    """
    Schema for a given Volume (A collection of Books with the same name)
    """

    name: str
    version: str
    description: Optional[str]
    license: str
    metadata: Dict[str, Any]  # TODO: type this
    dataset: Optional[Dict[str, Any]]  # TODO: type this
