"""Bundle-backed adapter for the producer write surface.

Reads stay live against the API, so ``used=`` resolves to real resources.
Every write lands in the bundle instead of reaching the platform.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from bookshelf._core.client import BookshelfClient
from bookshelf._core.config import UNSET, AuthInput
from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.activities import Activity
from bookshelf._produce.books import DraftBook
from bookshelf._produce.helpers import activity_envelope, used_ref, uuid7
from bookshelf._produce.helpers import resource_type as _resource_type
from bookshelf._produce.helpers import runner as _runner
from bookshelf._produce.helpers import visibility as _visibility
from bookshelf._produce.resources import Resource
from bookshelf._produce.serialise import SerialisedObject, serialise
from bookshelf._produce.types import HasTrackingId, RegisterItem, UsedInput
from bookshelf._produce.visibility import INHERIT, VisibilityInput
from bookshelf.cache import ContentCache
from bookshelf.facade import Bookshelf
from bookshelf.publisher.bundle import (
    Bundle,
    BundleActivity,
    BundleBook,
    BundleUsedRef,
    resource_filename,
    synthesise_pointer_hash,
)
from bookshelf.publisher.recipe import resolve_book_visibility


@dataclass(frozen=True, slots=True)
class _PreparedRegistration:
    """One fully validated managed resource awaiting bundle commit."""

    entry: RegisterItem
    materialised: SerialisedObject
    resource_id: UUID
    resource_type: models.ResourceType
    visibility: models.Visibility


class RecordedResource(Resource):
    """Local resource handle returned by a recording activity."""

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        tracking_id: UUID,
        resource_type: models.ResourceType,
        hash_: str,
        *,
        name: str | None = None,
        visibility: models.Visibility = models.Visibility.hidden,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        location: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        super().__init__(
            client,
            cache,
            tracking_id,
            metadata=models.ResourceRead(
                tracking_id=tracking_id,
                type=resource_type,
                name=name,
                hash=hash_,
                visibility=visibility,
                tags=list(tags),
                metadata=dict(metadata or {}),
                owner_org_id="recording",
                locations=[] if location is None else [location],
                location_url=location,
                created_at=now,
                updated_at=now,
            ),
            resource_type=resource_type,
        )
        self.hash = hash_


class RecordingActivity(Activity):
    """Activity context that records generated resources without network writes."""

    def __init__(
        self,
        bundle: Bundle,
        client: BookshelfClient,
        cache: ContentCache,
        *,
        activity_id: UUID,
        kind: str,
        code_ref: str,
        config: Mapping[str, Any],
        runner_name: str,
        config_hash: str | None = None,
        default_visibility: models.Visibility = models.Visibility.hidden,
    ) -> None:
        self._bundle = bundle
        self._client = client
        self._cache = cache
        self.activity_id = activity_id
        self.kind = kind
        self.code_ref = code_ref
        self.config = dict(config)
        self.runner = runner_name
        self.config_hash = config_hash
        self.default_visibility = default_visibility
        self._envelope = activity_envelope(
            activity_id=activity_id,
            kind=kind,
            code_ref=code_ref,
            config=config,
            runner=runner_name,
            used=(),
            config_hash=config_hash,
        )
        self._used: list[BundleUsedRef] = []
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

    def register(
        self,
        obj: object,
        *,
        type: str | models.ResourceType,
        name: str | None = None,
        used: Sequence[UsedInput] = (),
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        format: str | None = None,
        dedupe: bool = True,
    ) -> RecordedResource:
        """Serialise an output once and append its bytes and provenance."""
        self._require_entered()
        resource_type = _resource_type(type)
        resource_visibility = _visibility(visibility, self.default_visibility)
        materialised = serialise(obj, type=resource_type.value)
        resource_id = tracking_id or uuid7()
        self._merge_used(used)
        self._bundle.set_activity(self._bundle_activity())
        self._bundle.add_resource(
            data=materialised.data,
            hash_=materialised.hash,
            type_=resource_type.value,
            tracking_id=resource_id,
            name=name,
            format_=format or materialised.format,
            visibility=resource_visibility.value,
            tags=list(tags),
            metadata=dict(metadata or {}),
            dedupe=dedupe,
            generated=True,
            used=list(self._used),
        )
        return RecordedResource(
            self._client,
            self._cache,
            resource_id,
            resource_type,
            materialised.hash,
            name=name,
            visibility=resource_visibility,
            tags=tags,
            metadata=metadata,
        )

    def register_many(
        self,
        entries: Sequence[RegisterItem],
        *,
        used: Sequence[UsedInput] = (),
        atomic: bool = True,
    ) -> list[Resource]:
        """Record a batch in declaration order.

        Atomic batches are fully materialised and validated in a temporary bundle
        before their manifest and bytes are promoted together.
        """
        self._require_entered()
        if not entries:
            return []
        if not atomic:
            return [
                self.register(
                    entry.obj,
                    type=entry.type,
                    name=entry.name,
                    used=used,
                    visibility=entry.visibility,
                    tags=entry.tags,
                    metadata=entry.metadata,
                    tracking_id=entry.tracking_id,
                    format=entry.format,
                    dedupe=entry.dedupe,
                )
                for entry in entries
            ]

        prepared = [self._prepare_registration(entry) for entry in entries]
        merged_used = list(self._used)
        for value in used:
            reference = _bundle_used_ref(value)
            if reference not in merged_used:
                merged_used.append(reference)

        previous_count = len(self._bundle.manifest.resources)
        with tempfile.TemporaryDirectory(prefix="bookshelf-record-batch-") as staging_dir:
            staged = Bundle(
                Path(staging_dir),
                manifest=self._bundle.manifest.model_copy(deep=True),
            )
            staged.set_activity(self._bundle_activity())
            # The merged inputs apply to the resources this batch adds.
            for item in prepared:
                staged.add_resource(
                    data=item.materialised.data,
                    hash_=item.materialised.hash,
                    type_=item.resource_type.value,
                    tracking_id=item.resource_id,
                    name=item.entry.name,
                    format_=item.entry.format or item.materialised.format,
                    visibility=item.visibility.value,
                    tags=list(item.entry.tags),
                    metadata=dict(item.entry.metadata or {}),
                    dedupe=item.entry.dedupe,
                    generated=True,
                    used=list(merged_used),
                )

            created: list[Path] = []
            try:
                self._bundle.resources_dir.mkdir(parents=True, exist_ok=True)
                for resource in staged.manifest.resources[previous_count:]:
                    destination = self._bundle.resources_dir / resource_filename(
                        resource.hash,
                        resource.type,
                    )
                    if destination.exists():
                        continue
                    created.append(destination)
                    destination.write_bytes(staged.resource_bytes(resource))
            except Exception:
                for path in created:
                    path.unlink(missing_ok=True)
                raise

            self._bundle.manifest = staged.manifest
            self._used = merged_used

        return [
            RecordedResource(
                self._client,
                self._cache,
                item.resource_id,
                item.resource_type,
                item.materialised.hash,
                name=item.entry.name,
                visibility=item.visibility,
                tags=item.entry.tags,
                metadata=item.entry.metadata,
            )
            for item in prepared
        ]

    def _prepare_registration(self, entry: RegisterItem) -> _PreparedRegistration:
        resource_type = _resource_type(entry.type)
        visibility = _visibility(entry.visibility, self.default_visibility)
        return _PreparedRegistration(
            entry=entry,
            materialised=serialise(entry.obj, type=resource_type.value),
            resource_id=entry.tracking_id or uuid7(),
            resource_type=resource_type,
            visibility=visibility,
        )

    def register_external(
        self,
        *,
        type: str | models.ResourceType,
        uri: str,
        hash: str | None = None,
        name: str | None = None,
        used: Sequence[UsedInput] = (),
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        tracking_id: UUID | None = None,
        dedupe: bool = True,
    ) -> RecordedResource:
        """Record an external output and its activity provenance."""
        self._require_entered()
        self._merge_used(used)
        self._bundle.set_activity(self._bundle_activity())
        return _record_pointer(
            self._bundle,
            self._client,
            self._cache,
            type=type,
            uri=uri,
            hash=hash,
            name=name,
            visibility=visibility,
            default_visibility=self.default_visibility,
            tags=tags,
            metadata=metadata,
            tracking_id=tracking_id,
            dedupe=dedupe,
            generated=True,
            used=self._used,
        )

    def _require_entered(self) -> None:
        if not self._entered:
            raise RuntimeError("register operations require an open activity block")

    def _merge_used(self, values: Sequence[UsedInput]) -> None:
        """Accumulate the activity's inputs, for the resources registered after this.

        Resources already recorded keep the inputs they were registered with.
        """
        for value in values:
            reference = _bundle_used_ref(value)
            if reference not in self._used:
                self._used.append(reference)

    def _bundle_activity(self) -> BundleActivity:
        return BundleActivity(
            activity_id=self._envelope.activity_id,
            kind=self._envelope.kind,
            code_ref=self._envelope.code_ref,
            config_hash=self._envelope.config_hash,
            parameters=dict(self._envelope.parameters or {}),
            runner=self._envelope.runner,
        )


class RecordedDraftBook(DraftBook):
    """Draft-book handle whose writes update the bundle manifest."""

    def __init__(
        self,
        bundle: Bundle,
        client: BookshelfClient,
        *,
        volume: str,
        version: str,
        visibility: models.Visibility,
        license: str,
        description: str | None,
        citation_doi: str | None,
        metadata: Mapping[str, Any] | None,
    ) -> None:
        self._bundle = bundle
        super().__init__(
            client,
            models.BookDetail(
                book_id=uuid7(),
                version=version,
                edition=0,
                status="draft",
                visibility=visibility,
                created_at=datetime.now(UTC),
                series_name=volume,
                description=description,
                license=license,
                citation_doi=citation_doi,
                metadata=dict(metadata or {}),
            ),
        )

    def attach(
        self,
        resource: HasTrackingId | str | UUID,
        *,
        name_in_book: str,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
    ) -> models.BookEntryAttachResponse:
        """Record a book-local name for a resource in this bundle."""
        tracking_id = (
            UUID(str(resource))
            if isinstance(resource, str | UUID)
            else UUID(str(resource.tracking_id))
        )
        self._bundle.add_book_entry(
            name_in_book=name_in_book,
            tracking_id=tracking_id,
            data_dictionary=data_dictionary,
        )
        return models.BookEntryAttachResponse(
            entry_id=uuid7(),
            book_id=self.book_id,
            tracking_id=tracking_id,
            name_in_book=name_in_book,
        )

    def publish(self) -> Self:
        """Mark the recorded book for publication during replay."""
        self._bundle.mark_book_published()
        self.metadata.status = "published"
        return self


class RecordingSink:
    """Bundle-backed adapter for producer writes."""

    def __init__(
        self,
        bundle: Bundle,
        client: BookshelfClient,
        cache: ContentCache,
        *,
        authors: Sequence[Mapping[str, Any]] = (),
        default_visibility: models.Visibility = models.Visibility.hidden,
    ) -> None:
        self.bundle = bundle
        self._client = client
        self._cache = cache
        self._authors = tuple(dict(author) for author in authors)
        self._activity_started = False
        self.default_visibility = default_visibility
        """The tier a registration takes when the build file names none.

        Seeded from the recipe and re-seeded by :meth:`draft_book`, so the book's
        declared tier is what its resources record as.
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
    ) -> RecordingActivity:
        """Open the normal activity surface over the recording adapter."""
        if self._activity_started:
            raise BookshelfError("a recorded build supports one activity block")
        self._activity_started = True
        if code_ref is None:
            from bookshelf._produce.provenance import derive_code_ref

            code_ref = derive_code_ref()
        return RecordingActivity(
            self.bundle,
            self._client,
            self._cache,
            activity_id=activity_id or uuid7(),
            kind=kind,
            code_ref=code_ref,
            config=dict(config or {}),
            runner_name=runner or _runner(),
            config_hash=config_hash,
            default_visibility=self.default_visibility,
        )

    def draft_book(
        self,
        volume: str,
        *,
        version: str,
        description: str | None = None,
        citation_doi: str | None = None,
        license: str | None = None,
        visibility: VisibilityInput = INHERIT,
        metadata: Mapping[str, Any] | None = None,
        bundle_hash: str | None = None,
        discovery: Mapping[str, Any] | None = None,
        authors: Sequence[Mapping[str, Any]] | None = None,
    ) -> RecordedDraftBook:
        """Record pre-edition book framing and return its local handle.

        The book's tier becomes the default for every resource this build records
        afterwards, under the rule :func:`~bookshelf.publisher.recipe.resolve_book_visibility` states.

        The resolved discovery values are recorded as they arrive,
        so the bundle is a complete record of what publishing will say
        and ``bookshelf validate`` can be read as one.
        """
        del bundle_hash
        if license is None:
            raise ValueError("recorded books require an explicit license")
        book_visibility = resolve_book_visibility(visibility, default=self.default_visibility)
        self.default_visibility = book_visibility
        credited = (
            [dict(author) for author in authors] if authors is not None else list(self._authors)
        )
        self.bundle.set_book(
            BundleBook(
                volume=volume,
                version=version,
                visibility=book_visibility.value,
                license=license,
                authors=credited,
                discovery=dict(discovery) if discovery else None,
                description=description,
                citation_doi=citation_doi,
                metadata=dict(metadata or {}),
            )
        )
        return RecordedDraftBook(
            self.bundle,
            self._client,
            volume=volume,
            version=version,
            visibility=book_visibility,
            license=license,
            description=description,
            citation_doi=citation_doi,
            metadata=metadata,
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
    ) -> RecordedResource:
        """Record a catalogued pointer without writing its bytes."""
        return _record_pointer(
            self.bundle,
            self._client,
            self._cache,
            type=type,
            uri=uri,
            hash=hash,
            name=name,
            visibility=visibility,
            default_visibility=self.default_visibility,
            tags=tags,
            metadata=metadata,
            tracking_id=tracking_id,
            dedupe=dedupe,
        )

    def record_document(
        self,
        data: bytes,
        *,
        name: str,
        metadata: Mapping[str, Any],
    ) -> RecordedResource:
        """Record execution evidence as an output of the captured activity.

        The recorder adds these documents itself, so the build file cannot pass a
        tier for them. They take the book's, which keeps a public book's evidence
        readable alongside the data it explains.
        """
        activity = self.bundle.manifest.activity
        if activity is None:
            raise BookshelfError("a recorded build requires an activity before execution documents")
        materialised = serialise(data, type="document")
        resource_id = uuid7()
        used = _recorded_activity_used(self.bundle)
        self.bundle.add_resource(
            data=materialised.data,
            hash_=materialised.hash,
            type_="document",
            tracking_id=resource_id,
            name=name,
            visibility=self.default_visibility.value,
            metadata=dict(metadata),
            dedupe=False,
            generated=True,
            used=used,
        )
        return RecordedResource(
            self._client,
            self._cache,
            resource_id,
            models.ResourceType.document,
            materialised.hash,
            name=name,
            visibility=self.default_visibility,
            metadata=metadata,
        )


class RecordingBookshelf(Bookshelf):
    """Bookshelf facade with live reads and bundle-backed writes."""

    def __init__(
        self,
        bundle: Bundle,
        base_url: str | None = None,
        *,
        auth: AuthInput = UNSET,
        authors: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        super().__init__(base_url, auth=auth)
        self.bundle = bundle
        # The sink's default tier stays ``hidden`` until draft_book seeds it from
        # the book. A build file reaches this facade only through setup, which
        # drafts the book first, so nothing registers against the placeholder.
        self.recording_sink = RecordingSink(
            bundle,
            self._client,
            self._cache,
            authors=authors,
        )
        # Every producer call moves to the recording adapter,
        # so reads stay live and writes land in the bundle.
        self.activity = self.recording_sink.activity
        self.register_external = self.recording_sink.register_external
        self.draft_book = self.recording_sink.draft_book


def _bundle_used_ref(value: UsedInput) -> BundleUsedRef:
    reference = used_ref(value)
    if isinstance(reference, models.UsedRefByTrackingId):
        return BundleUsedRef(tracking_id=reference.tracking_id)
    return BundleUsedRef(name=reference.resource_name)


def _record_pointer(
    bundle: Bundle,
    client: BookshelfClient,
    cache: ContentCache,
    *,
    type: str | models.ResourceType,
    uri: str,
    hash: str | None,
    name: str | None,
    visibility: VisibilityInput,
    default_visibility: models.Visibility,
    tags: Sequence[str],
    metadata: Mapping[str, Any] | None,
    tracking_id: UUID | None,
    dedupe: bool,
    generated: bool = False,
    used: Sequence[BundleUsedRef] = (),
) -> RecordedResource:
    """Append one pointer resource and return its local handle."""
    resource_type = _resource_type(type)
    resource_visibility = _visibility(visibility, default_visibility)
    resource_hash = hash or synthesise_pointer_hash(
        type_=resource_type.value,
        external_uri=uri,
    )
    resource_id = tracking_id or uuid7()
    bundle.add_pointer(
        external_uri=uri,
        hash_=resource_hash,
        type_=resource_type.value,
        tracking_id=resource_id,
        name=name,
        visibility=resource_visibility.value,
        tags=list(tags),
        metadata=dict(metadata or {}),
        dedupe=dedupe,
        generated=generated,
        used=list(used),
    )
    return RecordedResource(
        client,
        cache,
        resource_id,
        resource_type,
        resource_hash,
        name=name,
        visibility=resource_visibility,
        tags=tags,
        metadata=metadata,
        location=uri,
    )


def _recorded_activity_used(bundle: Bundle) -> list[BundleUsedRef]:
    """Return the ordered union of inputs recorded by activity outputs."""
    values: list[BundleUsedRef] = []
    for resource in bundle.manifest.resources:
        if resource.generated:
            for reference in resource.used:
                if reference not in values:
                    values.append(reference)
    return values


__all__ = [
    "RecordedDraftBook",
    "RecordedResource",
    "RecordingActivity",
    "RecordingBookshelf",
    "RecordingSink",
]
