"""The 0.4 consumer API, kept alive on top of the platform facade.

Every call here warns with a :class:`DeprecationWarning` and routes to :class:`bookshelf.Bookshelf`.
Data comes from the platform, never from the old S3 bucket,
so a ``remote_bookshelf`` URL is reported and then ignored.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bookshelf._consume.conversions import scmrun_class
from bookshelf._core.errors import NotFoundError
from bookshelf._generated import models
from bookshelf.cache import ContentCache
from bookshelf.facade import Book, BookEntry, Bookshelf

if TYPE_CHECKING:
    import pandas as pd
    from scmdata import ScmRun

_REMOVAL = "bookshelf 2.0"
_SHAPE_SUFFIXES = ("_wide", "_long")


class UnknownBook(ValueError):
    """An unknown book is requested."""


class UnknownVersion(ValueError):
    """An unknown version is requested."""

    def __init__(self, name: str, version: str | None):
        self.name = name
        self.version = version
        super().__init__()

    def __str__(self) -> str:
        return f"Could not find {self.name}@{self.version}"


class UnknownEdition(UnknownVersion):
    """An unknown edition is requested."""

    def __init__(self, name: str, version: str, edition: int):
        super().__init__(name, version)
        self.edition = edition

    def __str__(self) -> str:
        return f"Could not find {self.name}@{self.version} ed.{self.edition}"


def _deprecated(old: str, new: str) -> None:
    warnings.warn(
        f"{old} is deprecated and will be removed in {_REMOVAL}, use {new} instead",
        DeprecationWarning,
        stacklevel=3,
    )


class BookShelf:
    """The 0.4 ``BookShelf``, backed by the platform.

    ``path`` becomes the content cache directory.
    ``remote_bookshelf`` has no effect, because the platform is the only source now.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        remote_bookshelf: str | None = None,
    ):
        _deprecated("bookshelf.BookShelf", "bookshelf.Bookshelf")
        if remote_bookshelf is not None:
            warnings.warn(
                f"remote_bookshelf={remote_bookshelf!r} is ignored: bookshelf 1.x reads from "
                "the platform API, set BOOKSHELF_URL to choose a deployment",
                stacklevel=2,
            )
        self._bookshelf = Bookshelf()
        if path is not None:
            self._bookshelf._cache = ContentCache(Path(path))
        self.path = self._bookshelf._cache.base_dir
        self.remote_bookshelf = self._bookshelf._client._base_url

    def load(
        self,
        name: str,
        version: str | None = None,
        edition: int | None = None,
        force: bool = False,  # noqa: ARG002
    ) -> LocalBook:
        """Load a book, defaulting to the latest version and edition.

        ``force`` is accepted and ignored, because there is no metadata cache to refresh.
        """
        _deprecated("BookShelf.load()", "Bookshelf.book()")
        return LocalBook(self._resolve(name, version, edition))

    def _resolve(self, name: str, version: str | None, edition: int | None) -> Book:
        if version is None:
            version = self._versions(name)[-1]
        try:
            return self._bookshelf.book(name, version, edition=edition)
        except NotFoundError as exc:
            if edition is not None:
                raise UnknownEdition(name, version, edition) from exc
            raise UnknownVersion(name, version) from exc

    def _versions(self, name: str) -> list[str]:
        try:
            books = self._bookshelf.list_books(name)
        except NotFoundError as exc:
            raise UnknownBook(f"No metadata for {name!r}") from exc
        if not books:
            raise UnknownBook(f"No metadata for {name!r}")
        return list(dict.fromkeys(book.version for book in books))

    def list_versions(self, name: str) -> list[str]:
        """List the published versions of a volume, oldest first."""
        _deprecated("BookShelf.list_versions()", "Bookshelf.list_books()")
        return self._versions(name)

    def is_available(
        self,
        name: str,
        version: str | None = None,
        edition: int | None = None,
    ) -> bool:
        """Report whether a matching published book exists on the platform."""
        _deprecated("BookShelf.is_available()", "Bookshelf.book()")
        try:
            self._resolve(name, version, edition)
        except (UnknownBook, UnknownVersion):
            return False
        return True

    def is_cached(self, name: str, version: str, edition: int) -> bool:
        """Report whether every resource of a book is already in the local cache.

        The book itself still has to be resolved on the platform, so this is best effort.
        """
        _deprecated("BookShelf.is_cached()", "Resource.as_path()")
        try:
            book = self._resolve(name, version, edition)
        except (UnknownBook, UnknownVersion):
            return False
        cache = self._bookshelf._cache
        return all(cache.get(book[entry].metadata.hash) is not None for entry in book.entry_names)

    def list_books(self) -> list[str]:
        """Not supported in 0.4 either."""
        raise NotImplementedError


class LocalBook:
    """The 0.4 ``LocalBook``, reading each resource from the platform."""

    def __init__(self, book: Book):
        self._book = book
        self.name = book.metadata.volume_name
        self.version = book.metadata.version
        self.edition = book.metadata.edition

    def long_version(self) -> str:
        """Return the ``{version}_e{edition:03}`` identifier, for example ``v1.0.1_e002``."""
        return f"{self.version}_e{self.edition:03}"

    def metadata(self) -> dict[str, Any]:
        """Return a plain dict in the shape of the old ``datapackage.json`` descriptor."""
        _deprecated("LocalBook.metadata()", "Book.metadata")
        item = self._book.metadata
        return {
            "name": self.name,
            "version": self.version,
            "edition": self.edition,
            "private": item.visibility is not models.Visibility.public,
            "metadata": dict(item.metadata),
            "resources": [self._descriptor(name) for name in self._book.entry_names],
        }

    def _descriptor(self, name: str) -> dict[str, Any]:
        entry = self._book[name].entry
        return {
            "name": name,
            "timeseries_name": name,
            "type": entry.type.value if entry.type is not None else None,
            "tracking_id": str(entry.tracking_id),
        }

    def _entry(self, timeseries_name: str) -> BookEntry:
        candidates = [timeseries_name]
        for suffix in _SHAPE_SUFFIXES:
            if timeseries_name.endswith(suffix):
                candidates.append(timeseries_name.removesuffix(suffix))
        for candidate in candidates:
            if candidate in self._book.entry_names:
                return self._book[candidate]
        raise ValueError(f"Unknown timeseries '{timeseries_name}'")

    def timeseries(self, timeseries_name: str) -> ScmRun:
        """Return a timeseries resource as an :class:`scmdata.ScmRun`."""
        _deprecated("LocalBook.timeseries()", "BookEntry.as_scmrun()")
        run = scmrun_class()
        # The stored wide file is read whole, which the book scoped timeseries query caps.
        wide = self._entry(timeseries_name).as_resource().as_df()
        return run(wide.reset_index())

    def get_long_format_data(self, timeseries_name: str) -> pd.DataFrame:
        """Return a timeseries resource in the 0.4 long format."""
        _deprecated("LocalBook.get_long_format_data()", "BookEntry.as_long_df()")
        return self._entry(timeseries_name).as_resource().as_long_df(legacy_columns=True)


__all__ = ["BookShelf", "LocalBook", "UnknownBook", "UnknownEdition", "UnknownVersion"]
