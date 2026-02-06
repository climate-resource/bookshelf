"""Backend protocol for bookshelf data sources."""

from __future__ import annotations

import pathlib
from typing import Protocol

from bookshelf.schema import Edition, Version


class BookshelfBackend(Protocol):
    """Protocol defining how BookShelf interacts with a data source.

    Each backend maps its native data structures directly to these
    higher-level semantic operations, avoiding intermediate models
    like VolumeMeta that carry fields unused by the consumer.
    """

    def resolve_version(
        self,
        name: str,
        version: Version | None = None,
        edition: Edition | None = None,
    ) -> tuple[Version, Edition]:
        """
        Resolve a (name, version?, edition?) triple to a concrete (version, edition).

        If version is None, resolve to the latest non-private version.
        If edition is None, resolve to the latest edition of the given version.

        Raises
        ------
        UnknownBook
            Volume does not exist
        UnknownVersion
            Version not found in volume
        UnknownEdition
            Edition not found for version
        """
        ...

    def list_versions(self, name: str) -> list[Version]:
        """
        List all non-private versions for a volume.

        Raises
        ------
        UnknownBook
            Volume does not exist
        """
        ...

    def fetch_datapackage(
        self,
        name: str,
        version: Version,
        edition: Edition,
        local_path: pathlib.Path,
    ) -> pathlib.Path:
        """
        Fetch the datapackage.json for a specific book and save to local_path.

        Returns the path to the local datapackage.json file.

        Raises
        ------
        UnknownVersion
            Book not found
        """
        ...

    def download_resource(  # noqa: PLR0913
        self,
        name: str,
        version: Version,
        edition: Edition,
        filename: str,
        local_path: pathlib.Path,
        known_hash: str | None = None,
    ) -> None:
        """
        Download a single resource file to local_path.

        Uses known_hash for integrity verification and cache-skip if available.
        """
        ...

    def list_volumes(self) -> list[str]:
        """
        List all available volume names.

        May raise NotImplementedError for backends that don't support listing.
        """
        ...
