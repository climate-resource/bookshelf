"""Producer methods mixed into the public Bookshelf facades."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf._produce.activities import Activity, AsyncActivity
from bookshelf._produce.books import AsyncDraftBook, DraftBook
from bookshelf._produce.helpers import (
    raise_partial_registration as _raise_partial_registration,
)
from bookshelf._produce.helpers import (
    registered_resource_type as _registered_resource_type,
)
from bookshelf._produce.helpers import (
    registered_tracking_id as _registered_tracking_id,
)
from bookshelf._produce.helpers import (
    registration_results as _registration_results,
)
from bookshelf._produce.helpers import (
    resource_type as _resource_type,
)
from bookshelf._produce.helpers import (
    runner as _runner,
)
from bookshelf._produce.helpers import (
    uuid7 as _uuid7,
)
from bookshelf._produce.helpers import (
    visibility as _visibility,
)
from bookshelf._produce.provenance import derive_code_ref
from bookshelf._produce.resources import AsyncResource, Resource
from bookshelf._produce.visibility import INHERIT, VisibilityInput
from bookshelf.cache import ContentCache


class LiveSink:
    """Live synchronous adapter for producer writes."""

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        *,
        default_visibility: models.Visibility = models.Visibility.hidden,
    ) -> None:
        self._client = client
        self._cache = cache
        self.default_visibility = default_visibility

    def activity(
        self,
        *,
        code_ref: str | None = None,
        config: Mapping[str, Any] | None = None,
        kind: str = "run",
        runner: str | None = None,
        activity_id: UUID | None = None,
        config_hash: str | None = None,
    ) -> Activity:
        """Open an ambient producer activity with deterministic provenance."""
        return Activity(
            self._client,
            self._cache,
            activity_id=activity_id or _uuid7(),
            kind=kind,
            code_ref=code_ref or derive_code_ref(),
            config=dict(config or {}),
            runner=runner or _runner(),
            config_hash=config_hash,
            default_visibility=self.default_visibility,
        )

    def register_external(
        self,
        *,
        type: str | models.ResourceType,
        uri: str,
        hash: str | None = None,
        logical_key: str | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> Resource:
        """Catalogue an external pointer without attributing it to an activity."""
        resource_type = _resource_type(type)
        item = models.RegisterResourceItem(
            tracking_id=tracking_id or _uuid7(),
            type=resource_type,
            hash=hash,
            logical_key=logical_key,
            visibility=_visibility(visibility, self.default_visibility),
            tags=list(tags),
            metadata=dict(metadata or {}),
            external_uri=uri,
            dedupe=dedupe,
        )
        response = self._client.register_resources(
            models.RegisterResourcesRequest(items=[item], atomic=True)
        )
        successful, failures = _registration_results(response)
        _raise_partial_registration(successful, failures)
        outcome = successful[0].outcome
        return Resource(
            self._client,
            self._cache,
            _registered_tracking_id(outcome),
            resource_type=_registered_resource_type(outcome, resource_type),
            registration_outcome=outcome,
        )

    def draft_book(
        self,
        volume: str,
        *,
        version: str,
        description: str | None = None,
        citation_doi: str | None = None,
        license: str | None = None,
        visibility: str | models.Visibility = models.Visibility.hidden,
        metadata: Mapping[str, Any] | None = None,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
        bundle_hash: str | None = None,
    ) -> DraftBook:
        """Create a mutable draft whose membership changes remain intentional calls."""
        detail = self._client.draft_book(
            models.BookDraftRequest(
                series_name=volume,
                version=version,
                description=description,
                citation_doi=(
                    models.CitationDoi(root=citation_doi) if citation_doi is not None else None
                ),
                license=models.License(root=license) if license is not None else None,
                visibility=_visibility(visibility),
                metadata=dict(metadata or {}),
                data_dictionary=list(data_dictionary or []),
                bundle_hash=(
                    models.BundleHash(root=bundle_hash) if bundle_hash is not None else None
                ),
            )
        )
        return DraftBook(self._client, detail)


class AsyncLiveSink:
    """Live asynchronous adapter for producer writes."""

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        *,
        default_visibility: models.Visibility = models.Visibility.hidden,
    ) -> None:
        self._client = client
        self._cache = cache
        self.default_visibility = default_visibility

    def activity(
        self,
        *,
        code_ref: str | None = None,
        config: Mapping[str, Any] | None = None,
        kind: str = "run",
        runner: str | None = None,
        activity_id: UUID | None = None,
        config_hash: str | None = None,
    ) -> AsyncActivity:
        """Open an ambient asynchronous producer activity."""
        return AsyncActivity(
            self._client,
            self._cache,
            activity_id=activity_id or _uuid7(),
            kind=kind,
            code_ref=code_ref or derive_code_ref(),
            config=dict(config or {}),
            runner=runner or _runner(),
            config_hash=config_hash,
            default_visibility=self.default_visibility,
        )

    async def register_external(
        self,
        *,
        type: str | models.ResourceType,
        uri: str,
        hash: str | None = None,
        logical_key: str | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> AsyncResource:
        """Catalogue an external pointer without attributing it to an activity."""
        resource_type = _resource_type(type)
        item = models.RegisterResourceItem(
            tracking_id=tracking_id or _uuid7(),
            type=resource_type,
            hash=hash,
            logical_key=logical_key,
            visibility=_visibility(visibility, self.default_visibility),
            tags=list(tags),
            metadata=dict(metadata or {}),
            external_uri=uri,
            dedupe=dedupe,
        )
        response = await self._client.register_resources_async(
            models.RegisterResourcesRequest(items=[item], atomic=True)
        )
        successful, failures = _registration_results(response)
        _raise_partial_registration(successful, failures)
        outcome = successful[0].outcome
        return AsyncResource(
            self._client,
            self._cache,
            _registered_tracking_id(outcome),
            resource_type=_registered_resource_type(outcome, resource_type),
            registration_outcome=outcome,
        )

    async def draft_book(
        self,
        volume: str,
        *,
        version: str,
        description: str | None = None,
        citation_doi: str | None = None,
        license: str | None = None,
        visibility: str | models.Visibility = models.Visibility.hidden,
        metadata: Mapping[str, Any] | None = None,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
        bundle_hash: str | None = None,
    ) -> AsyncDraftBook:
        """Create an asynchronous mutable draft book handle."""
        detail = await self._client.draft_book_async(
            models.BookDraftRequest(
                series_name=volume,
                version=version,
                description=description,
                citation_doi=(
                    models.CitationDoi(root=citation_doi) if citation_doi is not None else None
                ),
                license=models.License(root=license) if license is not None else None,
                visibility=_visibility(visibility),
                metadata=dict(metadata or {}),
                data_dictionary=list(data_dictionary or []),
                bundle_hash=(
                    models.BundleHash(root=bundle_hash) if bundle_hash is not None else None
                ),
            )
        )
        return AsyncDraftBook(self._client, detail)


class ProduceSink(Protocol):
    """Adapter interface for synchronous producer writes."""

    def activity(
        self,
        *,
        code_ref: str | None = None,
        config: Mapping[str, Any] | None = None,
        kind: str = "run",
        runner: str | None = None,
        activity_id: UUID | None = None,
        config_hash: str | None = None,
    ) -> Activity: ...

    def register_external(
        self,
        *,
        type: str | models.ResourceType,
        uri: str,
        hash: str | None = None,
        logical_key: str | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> Resource: ...

    def draft_book(
        self,
        volume: str,
        *,
        version: str,
        description: str | None = None,
        citation_doi: str | None = None,
        license: str | None = None,
        visibility: str | models.Visibility = models.Visibility.hidden,
        metadata: Mapping[str, Any] | None = None,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
        bundle_hash: str | None = None,
    ) -> DraftBook: ...


class AsyncProduceSink(Protocol):
    """Adapter interface for asynchronous producer writes."""

    def activity(
        self,
        *,
        code_ref: str | None = None,
        config: Mapping[str, Any] | None = None,
        kind: str = "run",
        runner: str | None = None,
        activity_id: UUID | None = None,
        config_hash: str | None = None,
    ) -> AsyncActivity: ...

    async def register_external(
        self,
        *,
        type: str | models.ResourceType,
        uri: str,
        hash: str | None = None,
        logical_key: str | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> AsyncResource: ...

    async def draft_book(
        self,
        volume: str,
        *,
        version: str,
        description: str | None = None,
        citation_doi: str | None = None,
        license: str | None = None,
        visibility: str | models.Visibility = models.Visibility.hidden,
        metadata: Mapping[str, Any] | None = None,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
        bundle_hash: str | None = None,
    ) -> AsyncDraftBook: ...


class ProduceFacade:
    """Synchronous producer operations layered onto the consume facade."""

    _produce_sink: ProduceSink

    def activity(
        self,
        *,
        code_ref: str | None = None,
        config: Mapping[str, Any] | None = None,
        kind: str = "run",
        runner: str | None = None,
        activity_id: UUID | None = None,
        config_hash: str | None = None,
    ) -> Activity:
        """Open an ambient producer activity."""
        return self._produce_sink.activity(
            code_ref=code_ref,
            config=config,
            kind=kind,
            runner=runner,
            activity_id=activity_id,
            config_hash=config_hash,
        )

    def register_external(
        self,
        *,
        type: str | models.ResourceType,
        uri: str,
        hash: str | None = None,
        logical_key: str | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> Resource:
        """Catalogue an external pointer through the active sink."""
        return self._produce_sink.register_external(
            type=type,
            uri=uri,
            hash=hash,
            logical_key=logical_key,
            visibility=visibility,
            tags=tags,
            metadata=metadata,
            tracking_id=tracking_id,
            dedupe=dedupe,
        )

    def draft_book(
        self,
        volume: str,
        *,
        version: str,
        description: str | None = None,
        citation_doi: str | None = None,
        license: str | None = None,
        visibility: str | models.Visibility = models.Visibility.hidden,
        metadata: Mapping[str, Any] | None = None,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
        bundle_hash: str | None = None,
    ) -> DraftBook:
        """Create a draft through the active sink.

        ``data_dictionary=`` describes the columns of the book's tabular and
        timeseries entries. It is applied when the draft is created, so a call
        that resumes an existing book through ``bundle_hash`` leaves the stored
        dictionary untouched.
        """
        return self._produce_sink.draft_book(
            volume,
            version=version,
            description=description,
            citation_doi=citation_doi,
            license=license,
            visibility=visibility,
            metadata=metadata,
            data_dictionary=data_dictionary,
            bundle_hash=bundle_hash,
        )


class AsyncProduceFacade:
    """Asynchronous producer operations layered onto the consume facade."""

    _produce_sink: AsyncProduceSink

    def activity(
        self,
        *,
        code_ref: str | None = None,
        config: Mapping[str, Any] | None = None,
        kind: str = "run",
        runner: str | None = None,
        activity_id: UUID | None = None,
        config_hash: str | None = None,
    ) -> AsyncActivity:
        """Open an ambient asynchronous producer activity."""
        return self._produce_sink.activity(
            code_ref=code_ref,
            config=config,
            kind=kind,
            runner=runner,
            activity_id=activity_id,
            config_hash=config_hash,
        )

    async def register_external(
        self,
        *,
        type: str | models.ResourceType,
        uri: str,
        hash: str | None = None,
        logical_key: str | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> AsyncResource:
        """Catalogue an external pointer through the active sink."""
        return await self._produce_sink.register_external(
            type=type,
            uri=uri,
            hash=hash,
            logical_key=logical_key,
            visibility=visibility,
            tags=tags,
            metadata=metadata,
            tracking_id=tracking_id,
            dedupe=dedupe,
        )

    async def draft_book(
        self,
        volume: str,
        *,
        version: str,
        description: str | None = None,
        citation_doi: str | None = None,
        license: str | None = None,
        visibility: str | models.Visibility = models.Visibility.hidden,
        metadata: Mapping[str, Any] | None = None,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
        bundle_hash: str | None = None,
    ) -> AsyncDraftBook:
        """Create a draft through the active sink.

        ``data_dictionary=`` describes the columns of the book's tabular and
        timeseries entries. It is applied when the draft is created, so a call
        that resumes an existing book through ``bundle_hash`` leaves the stored
        dictionary untouched.
        """
        return await self._produce_sink.draft_book(
            volume,
            version=version,
            description=description,
            citation_doi=citation_doi,
            license=license,
            visibility=visibility,
            metadata=metadata,
            data_dictionary=data_dictionary,
            bundle_hash=bundle_hash,
        )


__all__ = [
    "AsyncLiveSink",
    "AsyncProduceFacade",
    "AsyncProduceSink",
    "LiveSink",
    "ProduceFacade",
    "ProduceSink",
]
