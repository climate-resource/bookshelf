"""Bundle-backed adapter for the producer write surface.

Reads stay live against the API, so ``used=`` resolves to real resources.
Every write lands in the bundle instead of reaching the platform.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from bookshelf._core.client import BookshelfClient
from bookshelf._core.config import UNSET, AuthInput
from bookshelf._core.errors import BookshelfError
from bookshelf._core.names import validate_resource_name
from bookshelf._generated import models
from bookshelf._produce import helpers
from bookshelf._produce.activities import Activity
from bookshelf._produce.books import DraftBook
from bookshelf._produce.facade import ProcessingInput
from bookshelf._produce.provenance import canonical_config_hash, derive_activity_id
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
    resource_filename,
    synthesise_pointer_hash,
)
from bookshelf.publisher.recipe import ResolvedBook, resolve_book_visibility
from bookshelf.publisher.resource import LookupBook, ResolvedResource, resolve_resource

WRITE_ACTIVITY_KIND = "process"
"""The kind the implicit ``book.write`` activity records under.

Fixed because the kind lands in the manifest.
"""


@dataclass(frozen=True, slots=True)
class _PreparedRegistration:
    """One fully validated managed resource awaiting bundle commit."""

    entry: RegisterItem
    materialised: SerialisedObject
    resource_id: UUID
    resource_name: str
    resource_type: models.ResourceType
    visibility: models.Visibility


class RecordedResource(Resource):
    """Local resource handle returned by a recording activity.

    It carries the bundle-local ``name`` the manifest recorded it under,
    because that name is how replay addresses the resource
    and how a later registration cites it as an input.
    """

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        tracking_id: UUID,
        resource_type: models.ResourceType,
        hash_: str,
        *,
        name: str,
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
                hash=hash_,
                visibility=visibility,
                # The read shape, because this stands in for what the platform would return.
                discovery=models.ResourceDiscovery(tags=list(tags)),
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
        self.name = name


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
        names: dict[UUID, str],
        config_hash: str | None = None,
        default_visibility: models.Visibility = models.Visibility.hidden,
    ) -> None:
        self._bundle = bundle
        self._client = client
        self._cache = cache
        self._names = names
        self.activity_id = activity_id
        self.kind = kind
        self.code_ref = code_ref
        self.config = dict(config)
        self.runner = runner_name
        self.config_hash = config_hash
        self.default_visibility = default_visibility
        self._envelope = helpers.activity_envelope(
            activity_id=activity_id,
            kind=kind,
            code_ref=code_ref,
            config=config,
            runner=runner_name,
            used=(),
            config_hash=config_hash,
        )
        self._used: list[str] = []
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
        recorded_name = _recorded_name(name)
        resource_type = helpers.resource_type(type)
        resource_visibility = helpers.visibility(visibility, self.default_visibility)
        materialised = serialise(obj, type=resource_type.value)
        resource_id = tracking_id or helpers.uuid7()
        self._merge_used(used)
        self._bundle.set_activity(self._bundle_activity())
        self._bundle.add_resource(
            data=materialised.data,
            hash_=materialised.hash,
            type_=resource_type.value,
            name=recorded_name,
            format_=format or materialised.format,
            visibility=resource_visibility.value,
            tags=list(tags),
            metadata=dict(metadata or {}),
            dedupe=dedupe,
            generated=True,
            used=list(self._used),
        )
        self._names[resource_id] = recorded_name
        return RecordedResource(
            self._client,
            self._cache,
            resource_id,
            resource_type,
            materialised.hash,
            name=recorded_name,
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
        merged_used = self._merged_used_names(self._used, used)

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
                    name=item.resource_name,
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

        for item in prepared:
            self._names[item.resource_id] = item.resource_name
        return [
            RecordedResource(
                self._client,
                self._cache,
                item.resource_id,
                item.resource_type,
                item.materialised.hash,
                name=item.resource_name,
                visibility=item.visibility,
                tags=item.entry.tags,
                metadata=item.entry.metadata,
            )
            for item in prepared
        ]

    def _prepare_registration(self, entry: RegisterItem) -> _PreparedRegistration:
        resource_type = helpers.resource_type(entry.type)
        visibility = helpers.visibility(entry.visibility, self.default_visibility)
        return _PreparedRegistration(
            entry=entry,
            materialised=serialise(entry.obj, type=resource_type.value),
            resource_id=entry.tracking_id or helpers.uuid7(),
            resource_name=_recorded_name(entry.name),
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
            self._names,
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
        self._used = self._merged_used_names(self._used, values)

    def _merged_used_names(
        self,
        existing: Sequence[str],
        values: Sequence[UsedInput],
    ) -> list[str]:
        """Return ``existing`` extended with the names ``values`` adds, keeping first-seen order."""
        merged = list(existing)
        for value in values:
            name = _used_name(value, self._names)
            if name not in merged:
                merged.append(name)
        return merged

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
        metadata: Mapping[str, Any] | None,
        names: dict[UUID, str],
        activity: Callable[[], Activity] | None = None,
    ) -> None:
        self._bundle = bundle
        self._names = names
        super().__init__(
            client,
            models.BookDetail(
                book_id=helpers.uuid7(),
                version=version,
                edition=0,
                status="draft",
                visibility=visibility,
                created_at=datetime.now(UTC),
                series_name=volume,
                discovery=models.BookDiscovery(description=description, license=license),
                metadata=dict(metadata or {}),
            ),
            activity=activity,
        )

    def attach(
        self,
        resource: HasTrackingId | str | UUID,
        *,
        name_in_book: str,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
    ) -> models.BookEntryAttachResponse:
        """Record the membership of a resource this bundle carries.

        The platform registers a replayed resource under the name its entry takes,
        so the two are one name and a resource attached under a different one is refused.
        """
        tracking_id = (
            UUID(str(resource))
            if isinstance(resource, str | UUID)
            else UUID(str(resource.tracking_id))
        )
        recorded = self._names.get(tracking_id)
        if recorded is None:
            raise ValueError(
                f"{name_in_book!r} names a resource this bundle does not record. "
                "A recorded book is made of the resources its own build registered."
            )
        if recorded != name_in_book:
            raise ValueError(
                f"resource {recorded!r} cannot be attached as {name_in_book!r}. "
                "A replayed resource is registered under the name its entry takes, "
                f"so register it as {name_in_book!r}."
            )
        self._bundle.add_book_entry(name=name_in_book, data_dictionary=data_dictionary)
        return models.BookEntryAttachResponse(
            entry_id=helpers.uuid7(),
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
        resolved: ResolvedBook | None = None,
        recipe_dir: Path | None = None,
        lookup_book: LookupBook | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        self.bundle = bundle
        self._parameters = dict(parameters or {})
        self._client = client
        self._cache = cache
        self._resolved = resolved
        self._recipe_dir = recipe_dir
        self._lookup_book = lookup_book
        self._authors = tuple(dict(author) for author in authors)
        self._open_activity: RecordingActivity | None = None
        # A handle carries a tracking id, and the manifest is keyed by name,
        # so this is what lets ``used=[handle]`` and ``attach(handle)`` resolve to a name.
        self._names: dict[UUID, str] = {}
        self._used_resources: dict[str, ResolvedResource] = {}
        self.default_visibility = default_visibility
        """The tier a registration takes when the build file names none.

        Seeded from the recipe and re-seeded by :meth:`draft_book`,
        so the book's declared tier is what its resources record as.
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
        """Open the normal activity surface over the recording adapter.

        A recorded bundle carries one activity,
        because ``POST /v1/bundles/replay`` takes one and names no activity per resource.
        A second block would therefore record provenance that publishing cannot carry.
        """
        if self._open_activity is not None:
            raise BookshelfError(
                "a recorded build carries one activity, and this build already opened one. "
                "The replay endpoint takes a single activity, so a second block would record "
                "provenance that publishing would drop. Register the rest of the outputs in "
                "the block that is already open, or through book.write."
            )
        if code_ref is None:
            from bookshelf._produce.provenance import derive_code_ref

            code_ref = derive_code_ref()
        parameters = dict(config or {})
        settled_hash = config_hash or canonical_config_hash(parameters)
        self._open_activity = RecordingActivity(
            self.bundle,
            self._client,
            self._cache,
            activity_id=activity_id
            or derive_activity_id(
                kind=kind,
                code_ref=code_ref,
                config_hash=settled_hash,
                parameters=parameters,
            ),
            kind=kind,
            code_ref=code_ref,
            config=parameters,
            runner_name=runner or helpers.runner(),
            names=self._names,
            config_hash=settled_hash,
            default_visibility=self.default_visibility,
        )
        return self._open_activity

    def writing_activity(self) -> RecordingActivity:
        """The single activity ``book.write`` registers through.

        The sugar and the layered form share one activity,
        so a build may mix them and still record the bundle the replay endpoint accepts.

        The implicit activity's ``kind`` and ``config`` are pinned rather than defaulted.
        Both land in the manifest, so anything that varied between two runs of one build
        would fail a golden for reasons that have nothing to do with the data.
        """
        if self._open_activity is None:
            self.activity(kind=WRITE_ACTIVITY_KIND, config=self._parameters)
        if self._open_activity is None:  # pragma: no cover - activity() always assigns
            raise BookshelfError("opening the implicit activity recorded nothing")
        return self._open_activity._open()

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
        processing: ProcessingInput | None = None,
    ) -> RecordedDraftBook:
        """Record pre-edition book framing and return its local handle.

        The book's tier becomes the default for every resource this build records
        afterwards, under the rule :func:`~bookshelf.publisher.recipe.resolve_book_visibility` states.

        The resolved discovery values are recorded as they arrive,
        so the bundle is a complete record of what publishing will say
        and ``bookshelf validate`` can be read as one.

        ``processing`` is recorded as provenance and is never sent on replay,
        because the replay request carries the activity itself
        and the server derives the book's fingerprint from it.
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
                metadata=dict(metadata or {}),
                processing=None if processing is None else [tuple(pair) for pair in processing],
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
            metadata=metadata,
            names=self._names,
            activity=self.writing_activity,
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
            self._names,
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

    def use(self, name: str) -> ResolvedResource:
        """Resolve the named resource of the recorded version.

        A fetched or checked-in resource is verified, cached and registered as a pointer.
        A ``bookshelf://`` resource is looked up instead, and registers nothing,
        because the platform already holds it.
        """
        if self._resolved is None:
            raise BookshelfError("this recording carries no version, so it declares no resources")
        # A declared resource is registered under its own name, so resolving it twice
        # would be one bundle-local name claimed twice rather than a second input.
        resolved = self._used_resources.get(name)
        if resolved is None:
            resolved = resolve_resource(
                name,
                resources=self._resolved.resources,
                doi=self._resolved.discovery.doi,
                recipe_dir=self._recipe_dir,
                cache=self._cache,
                register_external=self.register_external,
                lookup_book=self._lookup_book,
            )
            self._used_resources[name] = resolved
        return resolved

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
        resource_id = helpers.uuid7()
        used = _recorded_activity_used(self.bundle)
        self.bundle.add_resource(
            data=materialised.data,
            hash_=materialised.hash,
            type_="document",
            name=name,
            visibility=self.default_visibility.value,
            metadata=dict(metadata),
            dedupe=False,
            generated=True,
            used=used,
        )
        self._names[resource_id] = name
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
        resolved: ResolvedBook | None = None,
        recipe_dir: Path | None = None,
        parameters: Mapping[str, Any] | None = None,
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
            resolved=resolved,
            recipe_dir=recipe_dir,
            parameters=parameters,
            # A bookshelf reference is a read, so it goes through the same facade a consumer uses.
            lookup_book=self.book,
        )
        # Every producer call moves to the recording adapter,
        # so reads stay live and writes land in the bundle.
        self.activity = self.recording_sink.activity
        self.register_external = self.recording_sink.register_external
        self.draft_book = self.recording_sink.draft_book

    def use(self, name: str) -> ResolvedResource:
        """Resolve one resource the recorded version declares."""
        return self.recording_sink.use(name)


def _recorded_name(name: str | None) -> str:
    """Return the bundle-local name a registration records under.

    Replay addresses every resource by name, so a recorded one cannot go without.
    """
    if name is None:
        raise ValueError(
            "a recorded resource needs a name, which replay addresses it by. "
            "Pass name= to the registration."
        )
    return validate_resource_name(name)


def _used_name(value: UsedInput, names: Mapping[UUID, str]) -> str:
    """Resolve one recorded lineage input to the bundle-local name replay cites it by.

    A replay cites its inputs by name against the resources of that same request,
    so an input the bundle does not record has no coordinate to travel under.
    """
    reference = helpers.used_ref(value)
    if isinstance(reference, models.UsedRefByResourceName):
        return reference.resource_name
    name = names.get(reference.tracking_id)
    if name is None:
        raise ValueError(
            f"used= cites resource {reference.tracking_id}, which this bundle does not record. "
            "A replayed resource cites only the inputs the same bundle carries."
        )
    return name


def _record_pointer(
    bundle: Bundle,
    client: BookshelfClient,
    cache: ContentCache,
    names: dict[UUID, str],
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
    used: Sequence[str] = (),
) -> RecordedResource:
    """Append one pointer resource and return its local handle."""
    recorded_name = _recorded_name(name)
    resource_type = helpers.resource_type(type)
    resource_visibility = helpers.visibility(visibility, default_visibility)
    resource_hash = hash or synthesise_pointer_hash(
        type_=resource_type.value,
        external_uri=uri,
    )
    resource_id = tracking_id or helpers.uuid7()
    bundle.add_pointer(
        external_uri=uri,
        hash_=resource_hash,
        type_=resource_type.value,
        name=recorded_name,
        visibility=resource_visibility.value,
        tags=list(tags),
        metadata=dict(metadata or {}),
        dedupe=dedupe,
        generated=generated,
        used=list(used),
    )
    names[resource_id] = recorded_name
    return RecordedResource(
        client,
        cache,
        resource_id,
        resource_type,
        resource_hash,
        name=recorded_name,
        visibility=resource_visibility,
        tags=tags,
        metadata=metadata,
        location=uri,
    )


def _recorded_activity_used(bundle: Bundle) -> list[str]:
    """Return the ordered union of input names recorded by activity outputs."""
    values: list[str] = []
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
