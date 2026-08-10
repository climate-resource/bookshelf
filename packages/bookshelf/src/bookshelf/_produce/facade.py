"""Producer write adapters and the seam the public facades bind to."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

from pydantic import RootModel

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
    registration_results as _registration_results,
)
from bookshelf._produce.helpers import (
    resource_type as _resource_type,
)
from bookshelf._produce.helpers import (
    runner as _runner,
)
from bookshelf._produce.helpers import (
    single_success as _single_success,
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


def _as_model[T: RootModel[str]](model: type[T], value: str | None) -> T | None:
    """Wrap an optional string in the model its request field takes.

    An omitted value stays ``None`` so it never reaches the wire.
    """
    return None if value is None else model(value)


def _register_item(
    *,
    type: str | models.ResourceType,
    uri: str,
    hash: str | None,
    name: str | None,
    visibility: models.Visibility,
    tags: Sequence[str],
    metadata: Mapping[str, Any] | None,
    tracking_id: UUID | None,
    dedupe: bool,
) -> models.RegisterResourceItem:
    """Build the single-item registration an external pointer becomes."""
    return models.RegisterResourceItem(
        tracking_id=tracking_id or _uuid7(),
        type=_resource_type(type),
        hash=hash,
        name=name,
        visibility=visibility,
        tags=list(tags),
        metadata=dict(metadata or {}),
        external_uri=uri,
        dedupe=dedupe,
    )


_DISCOVERY_WIRE_NAMES = {"release_date": "source_release_date"}
"""The discovery fields the API spells differently from the recipe."""

_NESTED_DISCOVERY = frozenset(models.BookDiscoveryInput.model_fields)
"""The discovery fields the API nests. Whatever else a recipe resolves is baked on beside them."""


def nests_discovery(name: str) -> bool:
    """Whether the API carries this recipe field inside ``discovery`` rather than beside it."""
    return _DISCOVERY_WIRE_NAMES.get(name, name) in _NESTED_DISCOVERY


def _discovery_input(fields: Mapping[str, Any] | None) -> models.BookDiscoveryInput | None:
    """Build the nested discovery object from a mapping keyed by the recipe's own names.

    ``description`` and ``authors`` are baked onto the book too,
    but the API carries them at the top level, so they travel separately.
    A field left unset stays out of the object entirely,
    which keeps an omission distinct from a declared null.
    """
    if not fields:
        return None
    declared = {
        wire: value
        for name, value in fields.items()
        if (wire := _DISCOVERY_WIRE_NAMES.get(name, name)) in _NESTED_DISCOVERY
        and value is not None
    }
    return models.BookDiscoveryInput(**declared) if declared else None


def people(values: Sequence[Mapping[str, Any]]) -> list[models.Author]:
    """Validate a list of authors or maintainers, which share one shape."""
    return [models.Author.model_validate(dict(value)) for value in values]


def _author_models(
    authors: Sequence[Mapping[str, Any]] | None,
) -> list[models.Author] | None:
    """Wrap the credited people as the API's author objects.

    An empty sequence reads the same as none at all.
    """
    return people(authors) if authors else None


def _draft_request(
    volume: str,
    *,
    version: str,
    description: str | None,
    license: str | None,
    visibility: models.Visibility,
    metadata: Mapping[str, Any] | None,
    bundle_hash: str | None,
    discovery: Mapping[str, Any] | None = None,
    authors: Sequence[Mapping[str, Any]] | None = None,
) -> models.BookDraftRequest:
    """Build the draft request, wrapping each optional string the API takes as a model.

    ``discovery`` carries the values a recipe resolved for this version,
    keyed by the recipe's field names.
    They are baked onto the book, so a later version never rewrites what this one says.
    """
    baked: dict[str, Any] = {}
    discovery_input = _discovery_input(discovery)
    if discovery_input is not None:
        baked["discovery"] = discovery_input
    author_models = _author_models(authors)
    if author_models is not None:
        baked["authors"] = author_models
    return models.BookDraftRequest(
        series_name=volume,
        version=version,
        description=description,
        license=_as_model(models.License, license),
        visibility=visibility,
        metadata=dict(metadata or {}),
        bundle_hash=_as_model(models.BundleHash, bundle_hash),
        **baked,
    )


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
        name: str | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> Resource:
        """Catalogue an external pointer without attributing it to an activity."""
        item = _register_item(
            type=type,
            uri=uri,
            hash=hash,
            name=name,
            visibility=_visibility(visibility, self.default_visibility),
            tags=tags,
            metadata=metadata,
            tracking_id=tracking_id,
            dedupe=dedupe,
        )
        response = self._client.register_resources(
            models.RegisterResourcesRequest(items=[item], atomic=True)
        )
        successful, failures = _registration_results(response)
        _raise_partial_registration(successful, failures)
        outcome = _single_success(successful)
        return Resource(
            self._client,
            self._cache,
            tracking_id=outcome.tracking_id,
            resource_type=_registered_resource_type(outcome, item.type),
            registration_outcome=outcome,
        )

    def draft_book(
        self,
        volume: str,
        *,
        version: str,
        description: str | None = None,
        license: str | None = None,
        visibility: VisibilityInput = INHERIT,
        metadata: Mapping[str, Any] | None = None,
        bundle_hash: str | None = None,
        discovery: Mapping[str, Any] | None = None,
        authors: Sequence[Mapping[str, Any]] | None = None,
    ) -> DraftBook:
        """Create a mutable draft whose membership changes remain intentional calls."""
        detail = self._client.draft_book(
            _draft_request(
                volume,
                version=version,
                description=description,
                license=license,
                visibility=_visibility(visibility, self.default_visibility),
                metadata=metadata,
                bundle_hash=bundle_hash,
                discovery=discovery,
                authors=authors,
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
        name: str | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> AsyncResource:
        """Catalogue an external pointer without attributing it to an activity."""
        item = _register_item(
            type=type,
            uri=uri,
            hash=hash,
            name=name,
            visibility=_visibility(visibility, self.default_visibility),
            tags=tags,
            metadata=metadata,
            tracking_id=tracking_id,
            dedupe=dedupe,
        )
        response = await self._client.register_resources_async(
            models.RegisterResourcesRequest(items=[item], atomic=True)
        )
        successful, failures = _registration_results(response)
        _raise_partial_registration(successful, failures)
        outcome = _single_success(successful)
        return AsyncResource(
            self._client,
            self._cache,
            tracking_id=outcome.tracking_id,
            resource_type=_registered_resource_type(outcome, item.type),
            registration_outcome=outcome,
        )

    async def draft_book(
        self,
        volume: str,
        *,
        version: str,
        description: str | None = None,
        license: str | None = None,
        visibility: VisibilityInput = INHERIT,
        metadata: Mapping[str, Any] | None = None,
        bundle_hash: str | None = None,
        discovery: Mapping[str, Any] | None = None,
        authors: Sequence[Mapping[str, Any]] | None = None,
    ) -> AsyncDraftBook:
        """Create an asynchronous mutable draft book handle."""
        detail = await self._client.draft_book_async(
            _draft_request(
                volume,
                version=version,
                description=description,
                license=license,
                visibility=_visibility(visibility, self.default_visibility),
                metadata=metadata,
                bundle_hash=bundle_hash,
                discovery=discovery,
                authors=authors,
            )
        )
        return AsyncDraftBook(self._client, detail)


class _ProduceSink[ActivityT, ResourceT, DraftT](Protocol):
    """Adapter interface for producer writes, parameterised by what each call hands back.

    The synchronous adapters return their handles directly.
    The asynchronous ones return an awaitable for the two calls that reach the API.
    """

    def activity(
        self,
        *,
        code_ref: str | None = None,
        config: Mapping[str, Any] | None = None,
        kind: str = "run",
        runner: str | None = None,
        activity_id: UUID | None = None,
        config_hash: str | None = None,
    ) -> ActivityT: ...

    def register_external(
        self,
        *,
        type: str | models.ResourceType,
        uri: str,
        hash: str | None = None,
        name: str | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> ResourceT: ...

    def draft_book(
        self,
        volume: str,
        *,
        version: str,
        description: str | None = None,
        license: str | None = None,
        visibility: VisibilityInput = INHERIT,
        metadata: Mapping[str, Any] | None = None,
        bundle_hash: str | None = None,
        discovery: Mapping[str, Any] | None = None,
        authors: Sequence[Mapping[str, Any]] | None = None,
    ) -> DraftT: ...


ProduceSink = _ProduceSink[Activity, Resource, DraftBook]
"""The synchronous producer seam, satisfied by :class:`LiveSink` and the recording adapter."""

AsyncProduceSink = _ProduceSink[AsyncActivity, Awaitable[AsyncResource], Awaitable[AsyncDraftBook]]
"""The asynchronous producer seam."""


__all__ = [
    "AsyncLiveSink",
    "AsyncProduceSink",
    "LiveSink",
    "ProduceSink",
]
