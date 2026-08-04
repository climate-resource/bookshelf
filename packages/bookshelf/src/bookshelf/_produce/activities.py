"""Activity contexts for registering produced resources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Self
from uuid import UUID

from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.helpers import (
    MAX_REGISTRATION_BATCH as _MAX_REGISTRATION_BATCH,
)
from bookshelf._produce.helpers import (
    activity_envelope as _activity_envelope,
)
from bookshelf._produce.helpers import (
    paired_successes as _paired_successes,
)
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
    single_success as _single_success,
)
from bookshelf._produce.helpers import (
    uuid7 as _uuid7,
)
from bookshelf._produce.helpers import (
    visibility as _visibility,
)
from bookshelf._produce.resources import AsyncResource, Resource
from bookshelf._produce.serialise import serialise
from bookshelf._produce.types import (
    PartialRegistrationError,
    RegisterItem,
    RegistrationFailure,
    RegistrationSuccess,
    UsedInput,
)
from bookshelf._produce.visibility import INHERIT, VisibilityInput
from bookshelf.cache import ContentCache


class Activity:
    """Synchronous activity context that attributes every produced resource."""

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        *,
        activity_id: UUID,
        kind: str,
        code_ref: str,
        config: Mapping[str, Any],
        runner: str,
        config_hash: str | None = None,
        default_visibility: models.Visibility = models.Visibility.hidden,
    ) -> None:
        self._client = client
        self._cache = cache
        self.activity_id = activity_id
        self.kind = kind
        self.code_ref = code_ref
        self.config = dict(config)
        self.runner = runner
        self.config_hash = config_hash
        self.default_visibility = default_visibility
        self._entered = False
        self._closed = False

    def __enter__(self) -> Self:
        if self._closed:
            raise RuntimeError("activity context cannot be re-entered after exit")
        if self._entered:
            raise RuntimeError("activity context is already entered")
        self._entered = True
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._entered = False
        self._closed = True

    def _require_entered(self) -> None:
        if not self._entered:
            raise RuntimeError("register operations require an open 'with bs.activity(...)' block")

    def register(
        self,
        obj: object,
        *,
        type: str | models.ResourceType,
        logical_key: str | None = None,
        used: Sequence[UsedInput] = (),
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        format: str | None = None,
        dedupe: bool = True,
    ) -> Resource:
        """Serialise, hash, upload, and register one generated resource.

        ``used=`` records the inputs consumed by this resource.
        """
        self._require_entered()
        return self.register_many(
            [
                RegisterItem(
                    obj=obj,
                    type=type,
                    logical_key=logical_key,
                    visibility=visibility,
                    tags=tags,
                    metadata=metadata,
                    tracking_id=tracking_id,
                    format=format,
                    dedupe=dedupe,
                )
            ],
            used=used,
        )[0]

    def register_many(
        self,
        entries: Sequence[RegisterItem],
        *,
        used: Sequence[UsedInput] = (),
        atomic: bool = True,
    ) -> list[Resource]:
        """Materialise many outputs, splitting only a non atomic oversized batch.

        ``used=`` records the inputs consumed by every output in this call.
        """
        self._require_entered()
        if atomic and len(entries) > _MAX_REGISTRATION_BATCH:
            raise ValueError(f"atomic registrations are limited to {_MAX_REGISTRATION_BATCH} items")
        items = [self._materialise(entry) for entry in entries]
        try:
            outcomes = self._register_items(items, used=used, atomic=atomic)
        except PartialRegistrationError as exc:
            exc.successful_resources = tuple(
                self._resource_from_success(success, items) for success in exc.successful
            )
            raise
        return [
            self._resource_from_outcome(outcome, item)
            for outcome, item in _paired_successes(outcomes, items)
        ]

    def register_external(
        self,
        *,
        type: str | models.ResourceType,
        uri: str,
        hash: str | None = None,
        logical_key: str | None = None,
        used: Sequence[UsedInput] = (),
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> Resource:
        """Register an external output and attribute it to this activity.

        ``used=`` records the inputs consumed by this resource.
        """
        self._require_entered()
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
        outcome = _single_success(self._register_items([item], used=used, atomic=True))
        return Resource(
            self._client,
            self._cache,
            _registered_tracking_id(outcome),
            resource_type=_registered_resource_type(outcome, resource_type),
            registration_outcome=outcome,
        )

    def _resource_from_outcome(
        self,
        outcome: models.RegistrationOutcome,
        item: models.RegisterResourceItem,
    ) -> Resource:
        return Resource(
            self._client,
            self._cache,
            _registered_tracking_id(outcome),
            resource_type=_registered_resource_type(outcome, item.type),
            registration_outcome=outcome,
        )

    def _resource_from_success(
        self,
        success: RegistrationSuccess,
        items: Sequence[models.RegisterResourceItem],
    ) -> Resource:
        return self._resource_from_outcome(success.outcome, items[success.index])

    def _materialise(self, entry: RegisterItem) -> models.RegisterResourceItem:
        resource_type = _resource_type(entry.type)
        serialised = serialise(entry.obj, type=resource_type.value)
        plan = self._client.initiate_ingest_upload(
            models.IngestUploadInitiateRequest(
                hash=serialised.hash,
                size_bytes=len(serialised.data),
                content_type=serialised.content_type,
            )
        )
        if isinstance(plan, models.UploadAlreadyExistsResponse):
            storage_path = plan.storage_path
        else:
            completed: list[models.UploadPartComplete] = []
            for part in plan.parts:
                content = serialised.data[part.start_byte : part.end_byte]
                etag = self._client.put_presigned(
                    part.presigned_url,
                    content,
                    content_type=serialised.content_type,
                )
                if plan.upload_id != "single":
                    if not etag:
                        raise BookshelfError(
                            f"presigned PUT for part {part.part_number} returned no ETag"
                        )
                    completed.append(
                        models.UploadPartComplete(
                            part_number=part.part_number,
                            etag=etag.strip('"'),
                        )
                    )
            if plan.upload_id != "single":
                self._client.complete_ingest_upload(
                    models.IngestUploadCompleteRequest(
                        upload_id=plan.upload_id,
                        storage_path=plan.storage_path,
                        parts=completed,
                    )
                )
            storage_path = plan.storage_path
        return models.RegisterResourceItem(
            tracking_id=entry.tracking_id or _uuid7(),
            type=resource_type,
            hash=serialised.hash,
            format=entry.format or serialised.format,
            logical_key=entry.logical_key,
            visibility=_visibility(entry.visibility, self.default_visibility),
            tags=list(entry.tags),
            metadata=dict(entry.metadata or {}),
            locations=[models.LocationInput(shelf="managed", path=storage_path)],
            dedupe=entry.dedupe,
        )

    def _register_items(
        self,
        items: Sequence[models.RegisterResourceItem],
        *,
        used: Sequence[UsedInput],
        atomic: bool,
    ) -> list[RegistrationSuccess]:
        if atomic and len(items) > _MAX_REGISTRATION_BATCH:
            raise ValueError(f"atomic registrations are limited to {_MAX_REGISTRATION_BATCH} items")
        chunk_size = _MAX_REGISTRATION_BATCH if not atomic else max(len(items), 1)
        successful: list[RegistrationSuccess] = []
        failures: list[RegistrationFailure] = []
        envelope = _activity_envelope(
            activity_id=self.activity_id,
            kind=self.kind,
            code_ref=self.code_ref,
            config=self.config,
            runner=self.runner,
            used=used,
            config_hash=self.config_hash,
        )
        for start in range(0, len(items), chunk_size):
            response = self._client.register_resources(
                models.RegisterResourcesRequest(
                    items=list(items[start : start + chunk_size]),
                    activity=envelope,
                    atomic=atomic,
                )
            )
            chunk_successful, chunk_failures = _registration_results(
                response,
                index_offset=start,
            )
            successful.extend(chunk_successful)
            failures.extend(chunk_failures)
        _raise_partial_registration(successful, failures)
        return successful


class AsyncActivity:
    """Asynchronous activity context that attributes every produced resource."""

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        *,
        activity_id: UUID,
        kind: str,
        code_ref: str,
        config: Mapping[str, Any],
        runner: str,
        config_hash: str | None = None,
        default_visibility: models.Visibility = models.Visibility.hidden,
    ) -> None:
        self._client = client
        self._cache = cache
        self.activity_id = activity_id
        self.kind = kind
        self.code_ref = code_ref
        self.config = dict(config)
        self.runner = runner
        self.config_hash = config_hash
        self.default_visibility = default_visibility
        self._entered = False
        self._closed = False

    async def __aenter__(self) -> Self:
        if self._closed:
            raise RuntimeError("activity context cannot be re-entered after exit")
        if self._entered:
            raise RuntimeError("activity context is already entered")
        self._entered = True
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._entered = False
        self._closed = True

    def _require_entered(self) -> None:
        if not self._entered:
            raise RuntimeError(
                "register operations require an open 'async with bs.activity(...)' block"
            )

    async def register(
        self,
        obj: object,
        *,
        type: str | models.ResourceType,
        logical_key: str | None = None,
        used: Sequence[UsedInput] = (),
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        format: str | None = None,
        dedupe: bool = True,
    ) -> AsyncResource:
        """Serialise, hash, upload, and register one generated resource.

        ``used=`` records the inputs consumed by this resource.
        """
        self._require_entered()
        resources = await self.register_many(
            [
                RegisterItem(
                    obj=obj,
                    type=type,
                    logical_key=logical_key,
                    visibility=visibility,
                    tags=tags,
                    metadata=metadata,
                    tracking_id=tracking_id,
                    format=format,
                    dedupe=dedupe,
                )
            ],
            used=used,
        )
        return resources[0]

    async def register_many(
        self,
        entries: Sequence[RegisterItem],
        *,
        used: Sequence[UsedInput] = (),
        atomic: bool = True,
    ) -> list[AsyncResource]:
        """Materialise many outputs, splitting only a non atomic oversized batch.

        ``used=`` records the inputs consumed by every output in this call.
        """
        self._require_entered()
        if atomic and len(entries) > _MAX_REGISTRATION_BATCH:
            raise ValueError(f"atomic registrations are limited to {_MAX_REGISTRATION_BATCH} items")
        items: list[models.RegisterResourceItem] = []
        for entry in entries:
            items.append(await self._materialise(entry))
        try:
            outcomes = await self._register_items(items, used=used, atomic=atomic)
        except PartialRegistrationError as exc:
            exc.successful_resources = tuple(
                self._resource_from_success(success, items) for success in exc.successful
            )
            raise
        return [
            self._resource_from_outcome(outcome, item)
            for outcome, item in _paired_successes(outcomes, items)
        ]

    async def register_external(
        self,
        *,
        type: str | models.ResourceType,
        uri: str,
        hash: str | None = None,
        logical_key: str | None = None,
        used: Sequence[UsedInput] = (),
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> AsyncResource:
        """Register an external output and attribute it to this activity.

        ``used=`` records the inputs consumed by this resource.
        """
        self._require_entered()
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
        outcome = _single_success(await self._register_items([item], used=used, atomic=True))
        return AsyncResource(
            self._client,
            self._cache,
            _registered_tracking_id(outcome),
            resource_type=_registered_resource_type(outcome, resource_type),
            registration_outcome=outcome,
        )

    def _resource_from_outcome(
        self,
        outcome: models.RegistrationOutcome,
        item: models.RegisterResourceItem,
    ) -> AsyncResource:
        return AsyncResource(
            self._client,
            self._cache,
            _registered_tracking_id(outcome),
            resource_type=_registered_resource_type(outcome, item.type),
            registration_outcome=outcome,
        )

    def _resource_from_success(
        self,
        success: RegistrationSuccess,
        items: Sequence[models.RegisterResourceItem],
    ) -> AsyncResource:
        return self._resource_from_outcome(success.outcome, items[success.index])

    async def _materialise(self, entry: RegisterItem) -> models.RegisterResourceItem:
        resource_type = _resource_type(entry.type)
        serialised = serialise(entry.obj, type=resource_type.value)
        plan = await self._client.initiate_ingest_upload_async(
            models.IngestUploadInitiateRequest(
                hash=serialised.hash,
                size_bytes=len(serialised.data),
                content_type=serialised.content_type,
            )
        )
        if isinstance(plan, models.UploadAlreadyExistsResponse):
            storage_path = plan.storage_path
        else:
            completed: list[models.UploadPartComplete] = []
            for part in plan.parts:
                content = serialised.data[part.start_byte : part.end_byte]
                etag = await self._client.put_presigned_async(
                    part.presigned_url,
                    content,
                    content_type=serialised.content_type,
                )
                if plan.upload_id != "single":
                    if not etag:
                        raise BookshelfError(
                            f"presigned PUT for part {part.part_number} returned no ETag"
                        )
                    completed.append(
                        models.UploadPartComplete(
                            part_number=part.part_number,
                            etag=etag.strip('"'),
                        )
                    )
            if plan.upload_id != "single":
                await self._client.complete_ingest_upload_async(
                    models.IngestUploadCompleteRequest(
                        upload_id=plan.upload_id,
                        storage_path=plan.storage_path,
                        parts=completed,
                    )
                )
            storage_path = plan.storage_path
        return models.RegisterResourceItem(
            tracking_id=entry.tracking_id or _uuid7(),
            type=resource_type,
            hash=serialised.hash,
            format=entry.format or serialised.format,
            logical_key=entry.logical_key,
            visibility=_visibility(entry.visibility, self.default_visibility),
            tags=list(entry.tags),
            metadata=dict(entry.metadata or {}),
            locations=[models.LocationInput(shelf="managed", path=storage_path)],
            dedupe=entry.dedupe,
        )

    async def _register_items(
        self,
        items: Sequence[models.RegisterResourceItem],
        *,
        used: Sequence[UsedInput],
        atomic: bool,
    ) -> list[RegistrationSuccess]:
        if atomic and len(items) > _MAX_REGISTRATION_BATCH:
            raise ValueError(f"atomic registrations are limited to {_MAX_REGISTRATION_BATCH} items")
        chunk_size = _MAX_REGISTRATION_BATCH if not atomic else max(len(items), 1)
        successful: list[RegistrationSuccess] = []
        failures: list[RegistrationFailure] = []
        envelope = _activity_envelope(
            activity_id=self.activity_id,
            kind=self.kind,
            code_ref=self.code_ref,
            config=self.config,
            runner=self.runner,
            used=used,
            config_hash=self.config_hash,
        )
        for start in range(0, len(items), chunk_size):
            response = await self._client.register_resources_async(
                models.RegisterResourcesRequest(
                    items=list(items[start : start + chunk_size]),
                    activity=envelope,
                    atomic=atomic,
                )
            )
            chunk_successful, chunk_failures = _registration_results(
                response,
                index_offset=start,
            )
            successful.extend(chunk_successful)
            failures.extend(chunk_failures)
        _raise_partial_registration(successful, failures)
        return successful


__all__ = ["Activity", "AsyncActivity"]
