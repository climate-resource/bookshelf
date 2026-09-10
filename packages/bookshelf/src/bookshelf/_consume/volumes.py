"""Volume handles, which answer what versions and editions a dataset has published."""

from __future__ import annotations

from collections.abc import Iterator
from textwrap import shorten

from bookshelf._consume.books import AsyncBook, Book
from bookshelf._consume.lookup import resolve_book, resolve_book_async
from bookshelf._consume.presentation import Section, Sections, summary_table, summary_text
from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import NotFoundError
from bookshelf._core.names import book_coordinate, version_key
from bookshelf._generated import models
from bookshelf.cache import ContentCache

_PUBLISHED = "published"
_DESCRIPTION_WIDTH = 68


def _plain(value: object) -> str | None:
    """Unwrap a discovery field, which the generated models wrap in a RootModel."""
    unwrapped = getattr(value, "root", value)
    return str(unwrapped) if unwrapped is not None else None


def _editions(info: models.VersionInfo) -> tuple[int, ...]:
    """The published editions of one version, oldest first."""
    return tuple(
        sorted(edition.edition for edition in info.editions if edition.status == _PUBLISHED)
    )


def _describe_editions(editions: tuple[int, ...]) -> str:
    """Say which editions a version has, as a range rather than a list."""
    if not editions:
        return "no published edition"
    if len(editions) == 1:
        return f"edition {editions[0]:03}"
    return f"editions {editions[0]:03}-{editions[-1]:03}"


class _VolumeBase:
    """Identity, versions and discovery for one volume, shared by both flavours."""

    _title = "Bookshelf Volume"

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        detail: models.VolumeDetailResponse,
    ) -> None:
        self._client = client
        self._cache = cache
        self.metadata = detail
        self.name = detail.name
        self._versions = {
            info.version: info
            for info in sorted(detail.versions, key=lambda info: version_key(info.version))
        }

    @property
    def versions(self) -> tuple[str, ...]:
        """Every version this volume has published, oldest first."""
        return tuple(self._versions)

    @property
    def latest(self) -> str | None:
        """The newest published version, or None for a volume that has published nothing."""
        return next(reversed(self._versions), None) if self._versions else None

    def editions(self, version: str) -> tuple[int, ...]:
        """The published editions of one version, oldest first."""
        return _editions(self._version(version))

    def __iter__(self) -> Iterator[str]:
        """Iterate over versions, oldest first."""
        return iter(self._versions)

    def __len__(self) -> int:
        return len(self._versions)

    def __contains__(self, version: str) -> bool:
        return version in self._versions

    def _version(self, version: str) -> models.VersionInfo:
        try:
            return self._versions[version]
        except KeyError:
            available = ", ".join(self._versions) or "(none)"
            raise NotFoundError(
                f"volume {self.name!r} has no version {version!r}, available: {available}",
                status_code=404,
            ) from None

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
        """Return the header and sections both reprs render, so the two cannot drift apart."""
        discovery = self.metadata.discovery
        stats = self.metadata.stats
        latest = self.latest
        volume: dict[str, object] = {
            "latest": book_coordinate(latest, max(self.editions(latest), default=None))
            if latest is not None
            else "(nothing published)",
            "license": _plain(discovery.license if discovery else None) or "(unstated)",
            "resources": stats.total_resources,
            "size": f"{stats.total_size_bytes / 1e6:.1f} MB",
        }
        description = _plain(discovery.description) if discovery is not None else None
        if description:
            volume["description"] = shorten(description, width=_DESCRIPTION_WIDTH)
        sections: dict[str, Section] = {
            "Volume": volume,
            "Versions": {
                version: _describe_editions(_editions(info))
                for version, info in self._versions.items()
            },
            "Access": [f'volume["{latest}"]' if latest is not None else 'volume["<version>"]'],
        }
        return f"{self._title} {self.name!r} (versions: {len(self._versions)})", sections

    def __repr__(self) -> str:
        return summary_text(*self._summary())

    def _repr_html_(self) -> str:
        return summary_table(*self._summary())


class Volume(_VolumeBase):
    """A volume indexed by version, resolving each into a published Book."""

    def book(self, version: str | None = None, *, edition: int | None = None) -> Book:
        """Resolve one published Book, defaulting to the newest version and edition."""
        return resolve_book(self._client, self._cache, self.name, self._resolve(version), edition)

    def __getitem__(self, version: str) -> Book:
        return self.book(version)


class AsyncVolume(_VolumeBase):
    """The asynchronous twin of :class:`Volume`."""

    _title = "Bookshelf Async Volume"

    async def book(self, version: str | None = None, *, edition: int | None = None) -> AsyncBook:
        """Resolve one published Book, defaulting to the newest version and edition."""
        return await resolve_book_async(
            self._client, self._cache, self.name, self._resolve(version), edition
        )


__all__ = ["AsyncVolume", "Volume"]
