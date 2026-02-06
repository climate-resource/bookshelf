"""API-based backend for bookshelf data sources."""

from __future__ import annotations

import json
import logging
import pathlib

from bookshelf.api.client import BookshelfAPIClient
from bookshelf.api.errors import NotFoundError
from bookshelf.errors import UnknownBook, UnknownEdition, UnknownVersion
from bookshelf.schema import Edition, Version

logger = logging.getLogger(__name__)


class APIBackend:
    """Backend that fetches data from the bookshelf REST API.

    Wraps BookshelfAPIClient and maps API response models directly
    to the BookshelfBackend protocol's return types.
    """

    def __init__(self, client: BookshelfAPIClient, local_cache: pathlib.Path):
        self.client = client
        self.local_cache = local_cache

    def resolve_version(
        self,
        name: str,
        version: Version | None = None,
        edition: Edition | None = None,
    ) -> tuple[Version, Edition]:
        """
        Resolve a (name, version?, edition?) triple to a concrete (version, edition).

        Maps VolumeDetailResponse -> (version, edition).
        Derives "private" from EditionInfo.status != "published".
        """
        try:
            detail = self.client.get_volume(name)
        except NotFoundError as err:
            raise UnknownBook(f"No metadata for {name!r}") from err

        if version is None:
            # Find latest non-private version
            # A version is "private" if NO edition has status == "published"
            published_versions = []
            for vi in detail.versions:
                if any(ei.status == "published" for ei in vi.editions):
                    published_versions.append(vi.version)
            if not published_versions:
                raise ValueError("No published volumes")
            version = sorted(published_versions)[-1]

        # Find matching VersionInfo
        matching_vi = None
        for vi in detail.versions:
            if vi.version == version:
                matching_vi = vi
                break
        if matching_vi is None:
            raise UnknownVersion(name, version)

        if edition is None:
            # Latest edition = highest edition number
            edition = sorted(matching_vi.editions, key=lambda e: e.edition)[-1].edition

        if edition not in [e.edition for e in matching_vi.editions]:
            raise UnknownEdition(name, version, edition)

        return version, edition

    def list_versions(self, name: str) -> list[Version]:
        """
        List all non-private versions for a volume.

        Maps VolumeDetailResponse -> list[str].
        A version is included if at least one edition has status == "published".
        """
        try:
            detail = self.client.get_volume(name)
        except NotFoundError as err:
            raise UnknownBook(f"No metadata for {name!r}") from err

        result = []
        for vi in detail.versions:
            if any(ei.status == "published" for ei in vi.editions):
                result.append(vi.version)
        return result

    def fetch_datapackage(
        self,
        name: str,
        version: Version,
        edition: Edition,
        local_path: pathlib.Path,
    ) -> pathlib.Path:
        """
        Fetch book metadata from API and write as datapackage.json.

        Maps BookResponse -> datapackage.json dict on disk.
        """
        try:
            book = self.client.get_book(name, version, edition)
        except NotFoundError as err:
            raise UnknownVersion(name, version) from err

        datapackage_dict: dict = {
            "name": name,
            "version": book.version,
            "edition": book.edition,
            "description": book.description,
            "private": book.private,
            "resources": [],
        }

        for resource in book.resources:
            resource_descriptor: dict = {
                "name": resource.name,
                "format": resource.format,
            }
            # Include enriched fields when available (from API Gap 1 resolution)
            if resource.filename is not None:
                resource_descriptor["filename"] = resource.filename
            if resource.hash is not None:
                resource_descriptor["hash"] = resource.hash
            if resource.download_url is not None:
                resource_descriptor["download_url"] = resource.download_url
            if resource.timeseries_name is not None:
                resource_descriptor["timeseries_name"] = resource.timeseries_name
            if resource.shape is not None:
                resource_descriptor["shape"] = resource.shape
            if resource.content_hash is not None:
                resource_descriptor["content_hash"] = resource.content_hash

            datapackage_dict["resources"].append(resource_descriptor)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "w") as f:
            json.dump(datapackage_dict, f, indent=2, default=str)

        return local_path

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
        Download a resource file using the API-provided download URL.

        Falls back to fetching the book metadata to find the download URL
        if not already available locally.
        """
        from bookshelf.utils import fetch_file  # noqa: PLC0415

        try:
            book = self.client.get_book(name, version, edition)
        except NotFoundError as err:
            raise UnknownVersion(name, version) from err

        # Find the resource with matching filename
        target_resource = None
        for resource in book.resources:
            if resource.filename == filename:
                target_resource = resource
                break

        if target_resource is None or target_resource.download_url is None:
            raise ValueError(f"Resource '{filename}' not found or missing download URL for {name}@{version}")

        fetch_file(
            target_resource.download_url,
            local_path,
            known_hash=known_hash or target_resource.hash,
        )

    def list_volumes(self) -> list[str]:
        """
        List all available volume names.

        Maps VolumeListResponse -> list[str].
        Handles pagination to collect all volumes.

        Note: BookShelf.list_books() calls this method. The naming is
        intentional: at the BookShelf level, "books" means "available
        named datasets" (i.e., volumes).
        """
        all_names: list[str] = []
        offset = 0
        limit = 100

        while True:
            response = self.client.list_volumes(limit=limit, offset=offset)
            all_names.extend(item.name for item in response.items)
            if not response.has_more:
                break
            offset += limit

        return all_names
