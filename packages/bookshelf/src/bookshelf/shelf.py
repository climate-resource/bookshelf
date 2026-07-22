"""
A BookShelf is a collection of Books that can be queried and fetched as needed.
"""

import json
import logging
import os
import pathlib
import re

from bookshelf.backends.protocol import BookshelfBackend
from bookshelf.backends.s3 import S3Backend
from bookshelf.book import LocalBook
from bookshelf.constants import DEFAULT_BACKEND
from bookshelf.errors import OfflineError, UnknownBook, UnknownEdition, UnknownVersion
from bookshelf.schema import Edition, Version, VolumeMeta
from bookshelf.utils import (
    build_url,
    create_local_cache,
    fetch_file,
    get_remote_bookshelf,
)

logger = logging.getLogger(__name__)


def fetch_volume_meta(
    name: str,
    remote_bookshelf: str,
    local_bookshelf: pathlib.Path,
    force: bool = True,
) -> VolumeMeta:
    """
    Fetch information about the books available for a given volume

    Parameters
    ----------
    name : str
        Name of the volume to fetch
    remote_bookshelf : str
        URL for the remote bookshelf
    local_bookshelf : pathlib.Path
        Local path where downloaded books will be stored.

        Must be a writable directory
    force: bool
        If True metadata is always fetched from the remote bookshelf

    Returns
    -------
    VolumeMeta
    """
    fname = "volume.json"

    local_fname = local_bookshelf / name / fname
    url = build_url(remote_bookshelf, name, fname)

    fetch_file(url, local_fname, force=force)

    with open(str(local_fname)) as file_handle:
        data = json.load(file_handle)

    return VolumeMeta(**data)


class BookShelf:
    """
    A BookShelf stores a number of Books

    If a Book isn't available locally, it will be queried from the remote bookshelf.

    Books can be fetched using [load][bookshelf.BookShelf.load] by name.
    Specific versions of a book can be pinned if needed,
    otherwise the latest version of the book is loaded.
    """

    def __init__(
        self,
        path: str | pathlib.Path | None = None,
        remote_bookshelf: str | None = None,
        backend: BookshelfBackend | None = None,
    ):
        if path is None:
            path = create_local_cache(path)
        self.path = pathlib.Path(path)
        self.remote_bookshelf = get_remote_bookshelf(remote_bookshelf)

        # If backend explicitly provided, use it. Otherwise check env var.
        if backend is not None:
            self._backend = backend
        elif os.environ.get("BOOKSHELF_BACKEND", DEFAULT_BACKEND).lower() == "api":
            from bookshelf.api.client import BookshelfAPIClient  # noqa: PLC0415
            from bookshelf.auth import get_api_url, get_token  # noqa: PLC0415
            from bookshelf.backends.api import APIBackend  # noqa: PLC0415

            self._backend = APIBackend(
                client=BookshelfAPIClient(
                    base_url=get_api_url(),
                    token=get_token(),
                ),
                local_cache=self.path,
            )
        else:
            self._backend = S3Backend(
                remote_bookshelf=self.remote_bookshelf,
                local_cache=self.path,
            )

    def load(
        self,
        name: str,
        version: Version | None = None,
        edition: Edition | None = None,
        force: bool = False,
    ) -> LocalBook:
        """
        Load a book

        If the book's metadata does not exist locally or an unknown version is requested
        the remote bookshelf is queried, otherwise the local metadata is used.

        When the backend is unreachable, falls back to cached data if available.

        Parameters
        ----------
        name: str
            Name of the volume to load
        version: str
            Version to load

            If no version is provided, the latest version is returned
        edition: int
            Edition of book to load

            If no edition is provided, the latest edition of the selected version is returned
        force: bool
            If True, redownload the book metadata

        Raises
        ------
        UnknownVersion
            The requested version is not available for the selected volume
        UnknownBook
            An invalid volume is requested
        OfflineError
            Network is unavailable and no cached data exists

        Returns
        -------
        :class:`LocalBook`
            A book from which the resources can be accessed
        """
        if version is None or edition is None or force:
            try:
                version, edition = self._backend.resolve_version(name, version, edition)
            except (ConnectionError, OSError) as exc:
                if force:
                    raise
                return self._offline_fallback(name, version, edition, exc)

        metadata_fragment = LocalBook.relative_path(name, version, edition, "datapackage.json")
        metadata_fname = self.path / metadata_fragment
        if not metadata_fname.exists() or force:
            try:
                self._backend.fetch_datapackage(name, version, edition, metadata_fname)
            except (ConnectionError, OSError) as exc:
                if force:
                    raise
                if metadata_fname.exists():
                    logger.warning(
                        "Network unavailable, using cached metadata for %s %s (edition %s)",
                        name,
                        version,
                        edition,
                    )
                    return LocalBook(name, version, edition, local_bookshelf=self.path)
                raise OfflineError(name, version) from exc

        if not metadata_fname.exists():
            raise AssertionError()
        return LocalBook(name, version, edition, local_bookshelf=self.path)

    def is_available(
        self,
        name: str,
        version: Version | None = None,
        edition: Edition | None = None,
    ) -> bool:
        """
        Check if a Book is available from the remote bookshelf

        Parameters
        ----------
        name : str
            Name of the volume to check
        version : str
            Version of the volume to check

            If no version is provided, then check if any Book's with a matching name
            have been uploaded.

        Returns
        -------
        bool
            True if a Book with a matching name and version exists on the remote bookshelf
        """
        try:
            self._resolve_version(name, version, edition)
        except (UnknownBook, UnknownVersion, UnknownEdition):
            return False
        return True

    def is_cached(self, name: str, version: Version, edition: Edition) -> bool:
        """
        Check if a book with a matching name/version is cached on the local bookshelf

        Parameters
        ----------
        name : str
            Name of the volume to check
        version : str
            Version of the volume to check
        edition : int
            Edition of the volume to check

        Returns
        -------
        bool
            True if a matching book is cached locally
        """
        try:
            # Check if the metadata for the book can be successfully read
            book = LocalBook(name, version, edition, local_bookshelf=self.path)
            book.metadata()
        except FileNotFoundError:
            return False
        return True

    def _resolve_version(
        self,
        name: str,
        version: Version | None = None,
        edition: Edition | None = None,
    ) -> tuple[Version, Edition]:
        return self._backend.resolve_version(name, version, edition)

    def list_versions(self, name: str) -> list[str]:
        """
        Get a list of available versions for a given Book

        Parameters
        ----------
        name: str
            Name of book

        Returns
        -------
        list of str
            List of available versions
        """
        return self._backend.list_versions(name)

    def list_books(self) -> list[str]:
        """
        Get a list of book names

        Returns
        -------
        list of str
            List of available books
        """
        return self._backend.list_volumes()

    def _offline_fallback(
        self,
        name: str,
        version: Version | None,
        edition: Edition | None,
        exc: Exception,
    ) -> LocalBook:
        """
        Attempt to return cached data when the backend is unreachable.

        Parameters
        ----------
        name
            Volume name
        version
            Requested version (may be None)
        edition
            Requested edition (may be None)
        exc
            The original connection error

        Raises
        ------
        OfflineError
            If no suitable cached data exists
        """
        # If version+edition were provided, check that specific cache entry
        if version is not None and edition is not None:
            if self.is_cached(name, version, edition):
                logger.warning(
                    "Network unavailable, using cached version of %s %s (edition %s)",
                    name,
                    version,
                    edition,
                )
                return self._load_from_cache(name, version, edition)

        # Fall back to any cached version
        cached = self._find_cached_versions(name)
        if cached:
            latest_version, latest_edition = cached[-1]
            logger.warning(
                "Network unavailable, falling back to cached %s %s (edition %s)",
                name,
                latest_version,
                latest_edition,
            )
            return self._load_from_cache(name, latest_version, latest_edition)

        raise OfflineError(name, version) from exc

    def _load_from_cache(self, name: str, version: Version, edition: Edition) -> LocalBook:
        """Load a book directly from the local cache without network calls."""
        return LocalBook(name, version, edition, local_bookshelf=self.path)

    def _find_cached_versions(self, name: str) -> list[tuple[Version, Edition]]:
        """
        Scan the local cache for cached versions of a volume.

        Returns a sorted list of (version, edition) tuples.
        """
        volume_dir = self.path / name
        if not volume_dir.is_dir():
            return []

        # Pattern: {version}_e{edition:03}
        version_edition_re = re.compile(r"^(.+)_e(\d{3})$")
        results: list[tuple[str, int]] = []

        for entry in sorted(volume_dir.iterdir()):
            if not entry.is_dir():
                continue
            match = version_edition_re.match(entry.name)
            if match and (entry / "datapackage.json").exists():
                results.append((match.group(1), int(match.group(2))))

        return results
