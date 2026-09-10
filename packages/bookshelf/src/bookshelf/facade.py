"""Thin public facades for consuming and producing Bookshelf data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self
from uuid import UUID

import httpx

from bookshelf._consume.books import AsyncBook, Book
from bookshelf._consume.integrity import HashMismatchError
from bookshelf._consume.lookup import (
    all_books,
    all_books_async,
    resolve_book,
    resolve_book_async,
)
from bookshelf._consume.memo import (
    book_ttl as _book_ttl,
)
from bookshelf._consume.memo import (
    default_book_ttl,
)
from bookshelf._consume.resources import (
    AsyncBookEntry,
    AsyncResource,
    BookEntry,
    Resource,
    UnsupportedConversionError,
)
from bookshelf._consume.volumes import AsyncVolume, Volume
from bookshelf._core.client import BookshelfClient
from bookshelf._core.config import UNSET, AuthInput
from bookshelf._core.errors import BookshelfError, NotFoundError
from bookshelf._generated import models
from bookshelf._produce import (
    Activity,
    AsyncActivity,
    AsyncDraftBook,
    DraftBook,
    PartialRegistrationError,
    RegisterItem,
    RegistrationFailure,
    RegistrationSuccess,
    Used,
)
from bookshelf._produce.facade import (
    AsyncLiveSink,
    AsyncProduceSink,
    LiveSink,
    ProduceSink,
)
from bookshelf._produce.facade import people as _people
from bookshelf.cache import ContentCache

if TYPE_CHECKING:
    from bookshelf.publisher.bundle import Bundle


def _volume_discovery(
    *,
    license: str | None = None,
    description: str | None = None,
    authors: Sequence[Mapping[str, Any]] | None = None,
    maintainers: Sequence[Mapping[str, Any]] | None = None,
    discovery: models.VolumeDiscoveryInput | None = None,
) -> models.VolumeDiscoveryInput | None:
    """Fold a volume's licence, description and credited people into its discovery profile.

    The API carries all four inside ``discovery`` now, with no top-level fields of their own.
    A ``discovery`` the caller passed is the starting point,
    and the dedicated parameters win over a same-named field already on it.
    """
    fields = discovery.model_dump(exclude_none=True) if discovery is not None else {}
    if license is not None:
        fields["license"] = license
    if description is not None:
        fields["description"] = description
    if authors is not None:
        fields["authors"] = _people(authors)
    if maintainers is not None:
        fields["maintainers"] = _people(maintainers)
    return models.VolumeDiscoveryInput(**fields) if fields else None


def _volume_create(
    name: str,
    *,
    license: str,
    description: str | None,
    metadata: Mapping[str, Any] | None,
    authors: Sequence[Mapping[str, Any]] | None,
    maintainers: Sequence[Mapping[str, Any]] | None,
    discovery: models.VolumeDiscoveryInput | None,
) -> models.VolumeCreate:
    """Build a create request carrying the name, the licence, and whatever else was named."""
    fields: dict[str, Any] = {}
    if metadata is not None:
        fields["metadata"] = dict(metadata)
    merged = _volume_discovery(
        license=license,
        description=description,
        authors=authors,
        maintainers=maintainers,
        discovery=discovery,
    )
    if merged is not None:
        fields["discovery"] = merged
    return models.VolumeCreate(name=name, **fields)


def _volume_update(
    *,
    description: str | None,
    metadata: Mapping[str, Any] | None,
    authors: Sequence[Mapping[str, Any]] | None,
    maintainers: Sequence[Mapping[str, Any]] | None,
    discovery: models.VolumeDiscoveryInput | None,
) -> models.VolumeUpdate:
    """Build a patch carrying only the fields the caller named.

    The licence has no parameter here, because it is fixed at creation and this never changes it.
    """
    fields: dict[str, Any] = {}
    if metadata is not None:
        fields["metadata"] = dict(metadata)
    merged = _volume_discovery(
        description=description,
        authors=authors,
        maintainers=maintainers,
        discovery=discovery,
    )
    if merged is not None:
        fields["discovery"] = merged
    return models.VolumeUpdate(**fields)


def _book_update(
    *,
    metadata: Mapping[str, Any] | None,
) -> models.BookUpdate:
    """Build a draft patch carrying only the fields the caller named.

    A draft's discovery profile is baked on at creation and cannot be revised here.
    """
    fields: dict[str, Any] = {}
    if metadata is not None:
        fields["metadata"] = dict(metadata)
    return models.BookUpdate(**fields)


def _one_resource(content_hash: str, items: Sequence[models.ResourceRead]) -> models.ResourceRead:
    """Pick the canonical resource a digest names, or say why there is not exactly one."""
    if not items:
        raise NotFoundError(
            f"no resource with hash {content_hash} in your organisation. "
            "Upload the file with 'bookshelf upload', or check the digest",
            status_code=404,
        )
    if len(items) > 1:
        raise BookshelfError(
            f"hash {content_hash} resolves to {len(items)} merging resources, "
            "where the platform promises one"
        )
    return items[0]


class Bookshelf:
    """Synchronous facade for consuming, cataloguing, and curating resources."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        auth: AuthInput = UNSET,
        timeout: float = 30.0,
        book_ttl: float | None = None,
        # The transport is the test seam: production always leaves it None.
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = BookshelfClient(
            base_url,
            auth=auth,
            timeout=timeout,
            transport=transport,
        )
        self._cache = ContentCache()
        self._book_ttl = default_book_ttl() if book_ttl is None else _book_ttl(book_ttl)
        # A subclass changes these by rebinding them after this runs, not by redefining them.
        sink: ProduceSink = LiveSink(self._client, self._cache)
        self.activity = sink.activity
        """Open an ambient producer activity with deterministic provenance."""
        self.register_external = sink.register_external
        """Catalogue an external pointer without attributing it to an activity."""
        self.register_file = sink.register_file
        """Upload a file and catalogue it as an input, attributing it to no activity."""
        self.draft_book = sink.draft_book
        """Create a mutable draft whose membership changes remain intentional calls."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the sync transport if it was opened."""
        self._client.close()

    def resource(self, tracking_id: str | UUID) -> Resource:
        """Resolve an exact tracking id into a lean Resource."""
        metadata = self._client.get_resource(tracking_id)
        return Resource(self._client, self._cache, tracking_id, metadata=metadata)

    def resource_by_hash(self, content_hash: str) -> Resource:
        """Resolve a content digest into the one resource your organisation holds for it.

        Book entries opt out of merging, so each edition owns its own row for the same bytes.
        The lookup asks for the canonical merging row alone, which is what a digest names.
        """
        response = self._client.list_resources(hash=content_hash, dedupe=True, limit=2)
        metadata = _one_resource(content_hash, response.items)
        return Resource(self._client, self._cache, metadata.tracking_id, metadata=metadata)

    def search_volumes(
        self,
        q: str | None = None,
        *,
        topic: Sequence[str] | None = None,
        keyword: Sequence[str] | None = None,
        region: Sequence[str] | None = None,
        publisher: str | None = None,
        license: str | None = None,
        coverage_year: int | None = None,
        resource_type: str | None = None,
        deprecated: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> models.VolumeListResponse:
        """Find volumes by free text over name, title and summary, plus discovery filters.

        Every filter combines with AND, and omitting all of them lists the catalogue.
        The response carries pagination, so a caller wanting everything reads
        ``has_more`` and pages with ``offset``.
        """
        return self._client.list_volumes(
            q=q,
            topic=topic,
            keyword=keyword,
            region=region,
            publisher=publisher,
            license=license,
            coverage_year=coverage_year,
            resource_type=resource_type,
            deprecated=deprecated,
            limit=limit,
            offset=offset,
        )

    def list_books(self, volume: str, *, status: str = "published") -> list[models.BookListItem]:
        """List every book in one volume, newest edition of each version last.

        This walks the pages itself,
        because a volume holds few enough books that a caller should not have to.
        """
        return all_books(self._client, volume, status=status)

    def volume(self, name: str) -> Volume:
        """Resolve a volume, carrying the versions and editions it has published."""
        return Volume(
            self._client, self._cache, self._client.get_volume(name), book_ttl=self._book_ttl
        )

    def create_volume(
        self,
        name: str,
        *,
        license: str,
        description: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        authors: Sequence[Mapping[str, Any]] | None = None,
        maintainers: Sequence[Mapping[str, Any]] | None = None,
        discovery: models.VolumeDiscoveryInput | None = None,
    ) -> models.VolumeResponse:
        """Create the volume a first publish needs, which drafting a book will not do for you.

        Creation needs WRITE and deletion needs ADMIN,
        so a caller can create a volume it cannot delete.
        """
        return self._client.create_volume(
            _volume_create(
                name,
                license=license,
                description=description,
                metadata=metadata,
                authors=authors,
                maintainers=maintainers,
                discovery=discovery,
            )
        )

    def update_volume(
        self,
        name: str,
        *,
        description: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        authors: Sequence[Mapping[str, Any]] | None = None,
        maintainers: Sequence[Mapping[str, Any]] | None = None,
        discovery: models.VolumeDiscoveryInput | None = None,
    ) -> models.VolumeResponse:
        """Update a volume's metadata, replacing each field named and leaving the rest alone.

        The licence is fixed at creation and cannot be changed here.
        A field can be changed but not cleared, because an omitted one stays off the wire.
        """
        return self._client.update_volume(
            name,
            _volume_update(
                description=description,
                metadata=metadata,
                authors=authors,
                maintainers=maintainers,
                discovery=discovery,
            ),
        )

    def delete_volume(self, name: str) -> None:
        """Delete a volume and every book in it.

        This needs ADMIN, which is a higher bar than the WRITE that creation needs,
        so the credential that created a volume may not be able to remove it.
        """
        self._client.delete_volume(name)

    def replay_bundle(self, bundle: Path | Bundle) -> models.BundleReplayResponse:
        """Upload a recorded bundle's managed bytes and replay it in one transactional request.

        Args:
            bundle: Bundle directory or an already loaded bundle.

        Returns:
            What the replay resolved to, the resulting book among it.
        """
        # Imported here because the publisher package imports this module.
        from bookshelf.publisher.replay import send_bundle

        return send_bundle(self._client, bundle)

    def discard_draft(self, book_id: str) -> None:
        """Delete a draft book, so a failed publish leaves no edition behind.

        Only a draft can be discarded.
        A published book is protected by the API and arrives back as an error.
        """
        self._client.delete_book(book_id)

    def update_draft(
        self,
        book_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> models.BookResponse:
        """Update a draft book's metadata, replacing what is named.

        Only a draft can be updated, so this is a fix before publishing rather than after.
        Its discovery profile is baked on at creation and is not revisable here.
        """
        return self._client.update_book(
            book_id,
            _book_update(
                metadata=metadata,
            ),
        )

    def book(self, volume: str, version: str, *, edition: int | None = None) -> Book:
        """Resolve a published Book, defaulting to the latest edition.

        A pinned edition is remembered on disk, so resolving it again makes no request
        until ``book_ttl`` seconds have passed.
        After that one request checks it is still published before it is trusted again.
        The latest edition is always asked for, because a newer one may have been published.
        """
        return resolve_book(
            self._client, self._cache, volume, version, edition, book_ttl=self._book_ttl
        )


class AsyncBookshelf:
    """Asynchronous facade for consuming, cataloguing, and curating resources."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        auth: AuthInput = UNSET,
        timeout: float = 30.0,
        book_ttl: float | None = None,
        # The transport is the test seam: production always leaves it None.
        async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = BookshelfClient(
            base_url,
            auth=auth,
            timeout=timeout,
            async_transport=async_transport,
        )
        self._cache = ContentCache()
        self._book_ttl = default_book_ttl() if book_ttl is None else _book_ttl(book_ttl)
        sink: AsyncProduceSink = AsyncLiveSink(self._client, self._cache)
        self.activity = sink.activity
        """Open an ambient asynchronous producer activity."""
        self.register_external = sink.register_external
        """Catalogue an external pointer without attributing it to an activity."""
        self.register_file = sink.register_file
        """Upload a file and catalogue it as an input, attributing it to no activity."""
        self.draft_book = sink.draft_book
        """Create an asynchronous mutable draft book handle."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close both transport surfaces if either was opened."""
        await self._client.aclose()

    async def resource(self, tracking_id: str | UUID) -> AsyncResource:
        """Resolve an exact tracking id into a lean async Resource."""
        metadata = await self._client.get_resource_async(tracking_id)
        return AsyncResource(self._client, self._cache, tracking_id, metadata=metadata)

    async def resource_by_hash(self, content_hash: str) -> AsyncResource:
        """Resolve a content digest into the one resource your organisation holds for it."""
        response = await self._client.list_resources_async(hash=content_hash, dedupe=True, limit=2)
        metadata = _one_resource(content_hash, response.items)
        return AsyncResource(self._client, self._cache, metadata.tracking_id, metadata=metadata)

    async def search_volumes(
        self,
        q: str | None = None,
        *,
        topic: Sequence[str] | None = None,
        keyword: Sequence[str] | None = None,
        region: Sequence[str] | None = None,
        publisher: str | None = None,
        license: str | None = None,
        coverage_year: int | None = None,
        resource_type: str | None = None,
        deprecated: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> models.VolumeListResponse:
        """Find volumes by free text over name, title and summary, plus discovery filters.

        Every filter combines with AND, and omitting all of them lists the catalogue.
        The response carries pagination, so a caller wanting everything reads
        ``has_more`` and pages with ``offset``.
        """
        return await self._client.list_volumes_async(
            q=q,
            topic=topic,
            keyword=keyword,
            region=region,
            publisher=publisher,
            license=license,
            coverage_year=coverage_year,
            resource_type=resource_type,
            deprecated=deprecated,
            limit=limit,
            offset=offset,
        )

    async def list_books(
        self,
        volume: str,
        *,
        status: str = "published",
    ) -> list[models.BookListItem]:
        """List every book in one volume, newest edition of each version last."""
        return await all_books_async(self._client, volume, status=status)

    async def volume(self, name: str) -> AsyncVolume:
        """Resolve a volume, carrying the versions and editions it has published."""
        return AsyncVolume(
            self._client,
            self._cache,
            await self._client.get_volume_async(name),
            book_ttl=self._book_ttl,
        )

    async def create_volume(
        self,
        name: str,
        *,
        license: str,
        description: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        authors: Sequence[Mapping[str, Any]] | None = None,
        maintainers: Sequence[Mapping[str, Any]] | None = None,
        discovery: models.VolumeDiscoveryInput | None = None,
    ) -> models.VolumeResponse:
        """Create the volume a first publish needs, which drafting a book will not do for you.

        Creation needs WRITE and deletion needs ADMIN,
        so a caller can create a volume it cannot delete.
        """
        return await self._client.create_volume_async(
            _volume_create(
                name,
                license=license,
                description=description,
                metadata=metadata,
                authors=authors,
                maintainers=maintainers,
                discovery=discovery,
            )
        )

    async def update_volume(
        self,
        name: str,
        *,
        description: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        authors: Sequence[Mapping[str, Any]] | None = None,
        maintainers: Sequence[Mapping[str, Any]] | None = None,
        discovery: models.VolumeDiscoveryInput | None = None,
    ) -> models.VolumeResponse:
        """Update a volume's metadata, replacing each field named and leaving the rest alone.

        The licence is fixed at creation and cannot be changed here.
        A field can be changed but not cleared, because an omitted one stays off the wire.
        """
        return await self._client.update_volume_async(
            name,
            _volume_update(
                description=description,
                metadata=metadata,
                authors=authors,
                maintainers=maintainers,
                discovery=discovery,
            ),
        )

    async def delete_volume(self, name: str) -> None:
        """Delete a volume and every book in it.

        This needs ADMIN, which is a higher bar than the WRITE that creation needs,
        so the credential that created a volume may not be able to remove it.
        """
        await self._client.delete_volume_async(name)

    async def replay_bundle(self, bundle: Path | Bundle) -> models.BundleReplayResponse:
        """Upload a recorded bundle's managed bytes and replay it in one transactional request.

        Args:
            bundle: Bundle directory or an already loaded bundle.

        Returns:
            What the replay resolved to, the resulting book among it.
        """
        # Imported here because the publisher package imports this module.
        from bookshelf.publisher.replay import send_bundle_async

        return await send_bundle_async(self._client, bundle)

    async def discard_draft(self, book_id: str) -> None:
        """Delete a draft book, so a failed publish leaves no edition behind.

        Only a draft can be discarded.
        A published book is protected by the API and arrives back as an error.
        """
        await self._client.delete_book_async(book_id)

    async def update_draft(
        self,
        book_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> models.BookResponse:
        """Update a draft book's metadata, replacing what is named.

        Only a draft can be updated, so this is a fix before publishing rather than after.
        Its discovery profile is baked on at creation and is not revisable here.
        """
        return await self._client.update_book_async(
            book_id,
            _book_update(
                metadata=metadata,
            ),
        )

    async def book(
        self,
        volume: str,
        version: str,
        *,
        edition: int | None = None,
    ) -> AsyncBook:
        """Resolve a published async Book, defaulting to the latest edition.

        The asynchronous twin of :meth:`Bookshelf.book`, with the same memoisation.
        """
        return await resolve_book_async(
            self._client, self._cache, volume, version, edition, book_ttl=self._book_ttl
        )


__all__ = [
    "Activity",
    "AsyncActivity",
    "AsyncBook",
    "AsyncBookEntry",
    "AsyncBookshelf",
    "AsyncDraftBook",
    "AsyncResource",
    "AsyncVolume",
    "Book",
    "BookEntry",
    "Bookshelf",
    "DraftBook",
    "HashMismatchError",
    "PartialRegistrationError",
    "RegisterItem",
    "RegistrationFailure",
    "RegistrationSuccess",
    "Resource",
    "UnsupportedConversionError",
    "Used",
    "Volume",
]
