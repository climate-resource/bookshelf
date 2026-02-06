"""S3-based backend for bookshelf data sources."""

from __future__ import annotations

import json
import logging
import pathlib

import requests.exceptions

from bookshelf.errors import UnknownBook, UnknownEdition, UnknownVersion
from bookshelf.schema import Edition, Version, VolumeMeta
from bookshelf.utils import build_url, fetch_file

logger = logging.getLogger(__name__)


class S3Backend:
    """Backend that fetches data from an S3-hosted static bookshelf.

    This extracts the existing S3-based logic from BookShelf and shelf.py
    into a standalone class satisfying the BookshelfBackend protocol.
    """

    def __init__(self, remote_bookshelf: str, local_cache: pathlib.Path):
        self.remote_bookshelf = remote_bookshelf
        self.local_cache = local_cache

    def _fetch_volume_meta(self, name: str) -> VolumeMeta:
        """Fetch volume.json from S3 and parse into VolumeMeta."""
        fname = "volume.json"
        local_fname = self.local_cache / name / fname
        url = build_url(self.remote_bookshelf, name, fname)

        fetch_file(url, local_fname, force=True)

        with open(str(local_fname)) as file_handle:
            data = json.load(file_handle)

        return VolumeMeta(**data)

    def resolve_version(
        self,
        name: str,
        version: Version | None = None,
        edition: Edition | None = None,
    ) -> tuple[Version, Edition]:
        """
        Resolve a (name, version?, edition?) triple to a concrete (version, edition).

        Extracted from shelf.py:203-228.
        """
        try:
            meta = self._fetch_volume_meta(name)
        except requests.exceptions.HTTPError as http_error:
            raise UnknownBook(f"No metadata for {name!r}") from http_error

        if version is None:
            version = meta.get_latest_version()

        matching_version_books = meta.get_version(version)
        if not matching_version_books:
            raise UnknownVersion(name, version)

        if edition is None:
            edition = matching_version_books[-1].edition
        if edition not in [b.edition for b in matching_version_books]:
            raise UnknownEdition(name, version, edition)

        return version, edition

    def list_versions(self, name: str) -> list[Version]:
        """
        List all non-private versions for a volume.

        Extracted from shelf.py:230-249.
        """
        try:
            meta = self._fetch_volume_meta(name)
        except requests.exceptions.HTTPError as http_error:
            raise UnknownBook(f"No metadata for {name!r}") from http_error

        return [v.version for v in meta.versions if not v.private]

    def fetch_datapackage(
        self,
        name: str,
        version: Version,
        edition: Edition,
        local_path: pathlib.Path,
    ) -> pathlib.Path:
        """
        Fetch datapackage.json from S3 and save to local_path.

        Extracted from shelf.py:128-139.
        """
        from bookshelf.book import LocalBook  # noqa: PLC0415

        url = build_url(
            self.remote_bookshelf,
            *LocalBook.path_parts(name, version, edition, "datapackage.json"),
        )
        try:
            fetch_file(url, local_fname=local_path, known_hash=None, force=False)
        except requests.exceptions.HTTPError as http_error:
            raise UnknownVersion(name, version) from http_error

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
        """Download a single resource file from S3."""
        from bookshelf.book import LocalBook  # noqa: PLC0415

        url = build_url(
            self.remote_bookshelf,
            *LocalBook.path_parts(name, version, edition, filename),
        )
        fetch_file(url, local_path, known_hash=known_hash)

    def list_volumes(self) -> list[str]:
        """S3 backend does not support listing volumes."""
        raise NotImplementedError
