"""Volume handles, which answer what versions and editions a dataset has published."""

from collections.abc import Iterator
from textwrap import shorten

from bookshelf._consume.books import AsyncBook, Book
from bookshelf._consume.lookup import resolve_book, resolve_book_async
from bookshelf._consume.presentation import Describable, Section, Sections, human_bytes
from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import NotFoundError
from bookshelf._core.names import book_coordinate, version_key
from bookshelf._generated import models
from bookshelf.cache import ContentCache

_PUBLISHED = "published"
_DESCRIPTION_WIDTH = 68


def _editions(info: models.VersionInfo) -> tuple[int, ...]:
    """The published editions of one version, oldest first."""
    return tuple(
        sorted(edition.edition for edition in info.editions if edition.status == _PUBLISHED)
    )


def _describe_editions(editions: tuple[int, ...]) -> str:
    """Say which editions a version has, as a range rather than a list."""
    if len(editions) == 1:
        return f"edition {editions[0]:03}"
    return f"editions {editions[0]:03}-{editions[-1]:03}"


class _VolumeBase(Describable):
    """Identity, versions and discovery for one volume, shared by both flavours."""

    _title = "Bookshelf Volume"
    _access = 'volume["{version}"]'

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        detail: models.VolumeDetailResponse,
        *,
        book_ttl: float,
    ) -> None:
        self._client = client
        self._cache = cache
        self._book_ttl = book_ttl
        self.metadata = detail
        """The volume's record as the platform returns it."""
        self.name = detail.name
        """The volume's name."""
        # Only versions with a published edition, because the rest resolve to no readable book.
        published = (
            (info.version, _editions(info))
            for info in sorted(detail.versions, key=lambda info: version_key(info.version))
        )
        self._versions = {version: editions for version, editions in published if editions}

    @property
    def versions(self) -> tuple[str, ...]:
        """Every version this volume has published, oldest first."""
        return tuple(self._versions)

    @property
    def latest(self) -> str | None:
        """The newest published version, or None for a volume that has published nothing."""
        return next(reversed(self._versions), None)

    def editions(self, version: str) -> tuple[int, ...]:
        """The published editions of one version, oldest first."""
        try:
            return self._versions[version]
        except KeyError:
            available = ", ".join(self._versions) or "(none)"
            raise NotFoundError(
                f"volume {self.name!r} has no version {version!r}, available: {available}",
                status_code=404,
            ) from None

    def __iter__(self) -> Iterator[str]:
        """Iterate over versions, oldest first."""
        return iter(self._versions)

    def __len__(self) -> int:
        """Count the published versions."""
        return len(self._versions)

    def __contains__(self, version: str) -> bool:
        """Whether this volume has published the version."""
        return version in self._versions

    def _resolve(self, version: str | None) -> str:
        """Settle which version a lookup means, defaulting to the newest."""
        if version is not None:
            return version
        latest = self.latest
        if latest is None:
            raise NotFoundError(
                f"volume {self.name!r} has published no book to resolve as the latest",
                status_code=404,
            )
        return latest

    def _summary(self) -> tuple[str, Sections]:
        discovery = self.metadata.discovery
        stats = self.metadata.stats
        latest = self.latest
        volume: dict[str, object] = {
            "latest": book_coordinate(latest, self.editions(latest)[-1])
            if latest is not None
            else "(nothing published)",
            "license": discovery.license.root if discovery and discovery.license else "(unstated)",
            "resources": stats.total_resources,
            "size": human_bytes(stats.total_size_bytes),
        }
        if discovery is not None and discovery.description:
            volume["description"] = shorten(discovery.description.root, width=_DESCRIPTION_WIDTH)
        sections: dict[str, Section] = {
            "Volume": volume,
            "Versions": {
                version: _describe_editions(editions)
                for version, editions in self._versions.items()
            },
            "Access": [self._access.format(version=latest if latest is not None else "<version>")],
        }
        return f"{self._title} {self.name!r} (versions: {len(self._versions)})", sections


class Volume(_VolumeBase):
    """A volume indexed by version, resolving each into a published Book."""

    def book(self, version: str | None = None, *, edition: int | None = None) -> Book:
        """Resolve one published Book, defaulting to the newest version and edition."""
        return resolve_book(
            self._client,
            self._cache,
            self.name,
            self._resolve(version),
            edition,
            book_ttl=self._book_ttl,
        )

    def __getitem__(self, version: str) -> Book:
        """Resolve the newest edition of one version, the same as ``book(version)``."""
        return self.book(version)


class AsyncVolume(_VolumeBase):
    """The asynchronous twin of :class:`Volume`."""

    _title = "Bookshelf Async Volume"
    # An index cannot be awaited, so the hint names the coroutine.
    _access = 'await volume.book("{version}")'

    async def book(self, version: str | None = None, *, edition: int | None = None) -> AsyncBook:
        """Resolve one published Book, defaulting to the newest version and edition."""
        return await resolve_book_async(
            self._client,
            self._cache,
            self.name,
            self._resolve(version),
            edition,
            book_ttl=self._book_ttl,
        )


__all__ = ["AsyncVolume", "Volume"]
