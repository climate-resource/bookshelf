"""Replay a recorded bundle through public facade primitives."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from bookshelf._produce.books import AsyncDraftBook, DraftBook
from bookshelf._produce.resources import AsyncResource, Resource
from bookshelf._produce.types import Used, UsedInput
from bookshelf.facade import AsyncBookshelf, Bookshelf
from bookshelf.publisher.bundle import (
    Bundle,
    BundleResource,
    BundleUsedRef,
    compute_book_bundle_hash,
)


async def replay_bundle(
    bundle: Path | Bundle,
    bs: AsyncBookshelf,
) -> AsyncDraftBook:
    """Replay a recorded bundle through an asynchronous Bookshelf client.

    Pass a :class:`pathlib.Path` for the usual publish workflow.
    The path must name a bundle directory containing its manifest and recorded resource bytes.
    Pass an already loaded :class:`Bundle`
    when the caller needs to inspect, validate, or transport the bundle before replay.

    The recorded activity and resource identifiers are sent verbatim.
    The book's content hash selects an existing published edition or a resumable draft,
    so repeating a replay is safe.
    If the manifest marks the book as published, this function publishes the draft.
    Otherwise it returns the populated draft without publishing it.

    Args:
        bundle: Bundle directory or an already loaded bundle.
        bs: Open asynchronous client used for all replay writes.

    Returns:
        The existing published book or the draft populated by this replay.

    Raises:
        ValueError: The bundle has no book framing or contains an invalid resource representation.
    """
    recorded = Bundle.read(bundle) if isinstance(bundle, Path) else bundle
    manifest = recorded.manifest
    book = manifest.book
    if book is None:
        raise ValueError("bundle has no book framing")
    draft = await bs.draft_book(
        book.volume,
        version=book.version,
        description=book.description,
        citation_doi=book.citation_doi,
        visibility=book.visibility,
        license=book.license,
        metadata=book.metadata,
        bundle_hash=compute_book_bundle_hash(manifest),
    )
    if draft.status == "published":
        return draft

    resources: dict[UUID, AsyncResource] = {}
    generated = [resource for resource in manifest.resources if resource.generated]
    inputs = [resource for resource in manifest.resources if not resource.generated]
    in_bundle = frozenset(resource.tracking_id for resource in manifest.resources)
    for resource in inputs:
        if resource.kind != "pointer" or resource.external_uri is None:
            raise ValueError("managed bundle resources require a recorded activity")
        resources[resource.tracking_id] = await bs.register_external(
            type=resource.type,
            uri=resource.external_uri,
            hash=resource.hash,
            logical_key=resource.logical_key,
            visibility=resource.visibility,
            tags=resource.tags,
            metadata=resource.metadata,
            tracking_id=resource.tracking_id,
            dedupe=resource.dedupe,
        )

    if manifest.activity is not None and generated:
        activity = manifest.activity
        async with bs.activity(
            activity_id=activity.activity_id,
            kind=activity.kind,
            code_ref=activity.code_ref,
            config=activity.parameters,
            runner=activity.runner,
            config_hash=activity.config_hash,
        ) as live_activity:
            for resource in generated:
                used = _resource_used(resource, resources, in_bundle)
                if resource.kind == "pointer":
                    if resource.external_uri is None:
                        raise ValueError(f"pointer {resource.tracking_id} has no external URI")
                    handle = await live_activity.register_external(
                        type=resource.type,
                        uri=resource.external_uri,
                        hash=resource.hash,
                        logical_key=resource.logical_key,
                        used=used,
                        visibility=resource.visibility,
                        tags=resource.tags,
                        metadata=resource.metadata,
                        tracking_id=resource.tracking_id,
                        dedupe=resource.dedupe,
                    )
                else:
                    handle = await live_activity.register(
                        recorded.resource_bytes(resource),
                        type=resource.type,
                        logical_key=resource.logical_key,
                        used=used,
                        visibility=resource.visibility,
                        tags=resource.tags,
                        metadata=resource.metadata,
                        tracking_id=resource.tracking_id,
                        format=resource.format,
                        dedupe=resource.dedupe,
                    )
                resources[resource.tracking_id] = handle
    elif generated:
        raise ValueError("generated bundle resources require a recorded activity")

    for entry in book.entries:
        await draft.attach(resources[entry.tracking_id], name_in_book=entry.name_in_book)
    if book.published:
        await draft.publish()
    return draft


def replay_bundle_sync(
    bundle: Path | Bundle,
    bs: Bookshelf,
) -> DraftBook:
    """Replay a recorded bundle through a synchronous Bookshelf client.

    This is the synchronous counterpart to :func:`replay_bundle`.
    It accepts the same path or loaded bundle forms.
    It preserves the same identifiers,
    lineage,
    draft-resume,
    and publication behaviour.
    """
    recorded = Bundle.read(bundle) if isinstance(bundle, Path) else bundle
    manifest = recorded.manifest
    book = manifest.book
    if book is None:
        raise ValueError("bundle has no book framing")
    draft = bs.draft_book(
        book.volume,
        version=book.version,
        description=book.description,
        citation_doi=book.citation_doi,
        visibility=book.visibility,
        license=book.license,
        metadata=book.metadata,
        bundle_hash=compute_book_bundle_hash(manifest),
    )
    if draft.status == "published":
        return draft

    resources: dict[UUID, Resource] = {}
    generated = [resource for resource in manifest.resources if resource.generated]
    inputs = [resource for resource in manifest.resources if not resource.generated]
    in_bundle = frozenset(resource.tracking_id for resource in manifest.resources)
    for resource in inputs:
        if resource.kind != "pointer" or resource.external_uri is None:
            raise ValueError("managed bundle resources require a recorded activity")
        resources[resource.tracking_id] = bs.register_external(
            type=resource.type,
            uri=resource.external_uri,
            hash=resource.hash,
            logical_key=resource.logical_key,
            visibility=resource.visibility,
            tags=resource.tags,
            metadata=resource.metadata,
            tracking_id=resource.tracking_id,
            dedupe=resource.dedupe,
        )

    if manifest.activity is not None and generated:
        activity = manifest.activity
        with bs.activity(
            activity_id=activity.activity_id,
            kind=activity.kind,
            code_ref=activity.code_ref,
            config=activity.parameters,
            runner=activity.runner,
            config_hash=activity.config_hash,
        ) as live_activity:
            for resource in generated:
                used = _resource_used(resource, resources, in_bundle)
                if resource.kind == "pointer":
                    if resource.external_uri is None:
                        raise ValueError(f"pointer {resource.tracking_id} has no external URI")
                    handle = live_activity.register_external(
                        type=resource.type,
                        uri=resource.external_uri,
                        hash=resource.hash,
                        logical_key=resource.logical_key,
                        used=used,
                        visibility=resource.visibility,
                        tags=resource.tags,
                        metadata=resource.metadata,
                        tracking_id=resource.tracking_id,
                        dedupe=resource.dedupe,
                    )
                else:
                    handle = live_activity.register(
                        recorded.resource_bytes(resource),
                        type=resource.type,
                        logical_key=resource.logical_key,
                        used=used,
                        visibility=resource.visibility,
                        tags=resource.tags,
                        metadata=resource.metadata,
                        tracking_id=resource.tracking_id,
                        format=resource.format,
                        dedupe=resource.dedupe,
                    )
                resources[resource.tracking_id] = handle
    elif generated:
        raise ValueError("generated bundle resources require a recorded activity")

    for entry in book.entries:
        draft.attach(resources[entry.tracking_id], name_in_book=entry.name_in_book)
    if book.published:
        draft.publish()
    return draft


def _resource_used(
    resource: BundleResource,
    registered: Mapping[UUID, Resource | AsyncResource],
    in_bundle: frozenset[UUID],
) -> list[UsedInput]:
    """Resolve one resource's recorded inputs against what replay actually registered.

    A recorded tracking id is a claim about the bundle, not about the deployment.
    The server may answer a registration with a resource it already holds when the
    bytes match, so an input is cited by the id that came back rather than the id
    the bundle asked for.

    A resource citing itself is dropped, which a bundle recorded before inputs were
    kept per resource will do.
    An id the bundle does not carry belongs to something registered elsewhere, so it
    passes through for the server to resolve.
    """
    values: list[UsedInput] = []
    seen: set[tuple[str, str]] = set()
    for reference in resource.used:
        value = _used_value(reference)
        if isinstance(value, UUID):
            if value == resource.tracking_id:
                continue
            handle = registered.get(value)
            if handle is not None:
                value = handle.tracking_id
            elif value in in_bundle:
                raise ValueError(
                    f"resource {resource.tracking_id} consumes {value}, "
                    "which the bundle records after it. "
                    "Inputs must be registered before whatever consumes them."
                )
        key = (
            ("tracking_id", str(value))
            if isinstance(value, UUID)
            else ("logical_key", value.logical_key)
        )
        if key not in seen:
            seen.add(key)
            values.append(value)
    return values


def _used_value(reference: BundleUsedRef) -> Used | UUID:
    if reference.tracking_id is not None:
        return reference.tracking_id
    if reference.logical_key is not None:
        return Used(logical_key=reference.logical_key)
    raise ValueError("recorded used reference has no coordinate")


__all__ = ["replay_bundle", "replay_bundle_sync"]
