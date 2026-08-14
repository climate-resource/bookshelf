"""Replay a recorded bundle through the platform's one-call replay endpoint.

``POST /v1/bundles/replay`` registers every resource,
mints the recorded activity's provenance edges,
drafts the book,
attaches every entry and publishes it,
all in one transaction that rolls back as a whole.
The client's job is therefore to put the managed bytes in place
and to project the manifest onto the request.

Every resource travels under its bundle-local name.
The server owns the name to tracking id mapping,
so nothing is carried between calls
and the manifest order is the contract:
an input is always registered before whatever consumes it.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf._produce.facade import discovery_input
from bookshelf._produce.serialise import content_type_for
from bookshelf._produce.uploads import upload_bytes, upload_bytes_async
from bookshelf.facade import AsyncBookshelf, Bookshelf
from bookshelf.publisher.bundle import (
    Bundle,
    BundleActivity,
    BundleBook,
    BundleBookEntry,
    BundleResource,
)


def _entry(entry: BundleBookEntry) -> models.ReplayEntry:
    """Project one recorded membership row, preserving omission versus clearing."""
    dictionary = (
        None
        if entry.data_dictionary is None
        else [models.DataDictionaryEntry.model_validate(item) for item in entry.data_dictionary]
    )
    return models.ReplayEntry(name=entry.name, data_dictionary=dictionary)


def _activity(activity: BundleActivity) -> models.ReplayActivity:
    """Project the recorded activity, under the id it was recorded with.

    Sending the id again is what lets a repeated replay find the same activity
    rather than mint duplicate provenance edges.
    """
    return models.ReplayActivity(
        activity_id=activity.activity_id,
        kind=activity.kind,
        code_ref=activity.code_ref,
        config_hash=activity.config_hash,
        parameters=dict(activity.parameters),
        runner=activity.runner,
    )


def _book(book: BundleBook) -> models.ReplayBook:
    """Project the recorded framing, folding the editorial fields into discovery."""
    return models.ReplayBook(
        volume=book.volume,
        version=book.version,
        visibility=models.Visibility(book.visibility),
        discovery=discovery_input(
            book.discovery,
            description=book.description,
            license=book.license,
            authors=book.authors,
        ),
        metadata=dict(book.metadata),
        entries=[_entry(entry) for entry in book.entries],
        published=book.published,
    )


def _resource(resource: BundleResource, storage_path: str | None) -> models.ReplayResource:
    """Project one recorded resource, addressing it and its inputs by name."""
    pointer = resource.kind == "pointer"
    return models.ReplayResource(
        name=resource.name,
        hash=resource.hash,
        type=models.ResourceType(resource.type),
        kind=models.Kind2(resource.kind),
        format=resource.format,
        visibility=models.Visibility(resource.visibility),
        discovery=models.ResourceDiscovery(tags=list(resource.tags)),
        metadata=dict(resource.metadata),
        dedupe=resource.dedupe,
        size_bytes=None if pointer else resource.size,
        external_uri=resource.external_uri,
        storage_path=None if pointer else storage_path,
        generated=resource.generated,
        used=list(resource.used),
    )


def _request(bundle: Bundle, storage_paths: Mapping[str, str]) -> models.BundleReplayRequest:
    """Build the one request a replay sends, in the recorded resource order."""
    manifest = bundle.manifest
    return models.BundleReplayRequest(
        activity=None if manifest.activity is None else _activity(manifest.activity),
        resources=[
            _resource(resource, storage_paths.get(resource.name)) for resource in manifest.resources
        ],
        book=None if manifest.book is None else _book(manifest.book),
    )


def _managed(bundle: Bundle) -> list[BundleResource]:
    """The recorded resources whose bytes the platform hosts."""
    return [resource for resource in bundle.manifest.resources if resource.kind == "managed"]


def send_bundle(client: BookshelfClient, bundle: Path | Bundle) -> models.BundleReplayResponse:
    """Upload the managed bytes and send the whole bundle as one request.

    This is the seam the facade drives, so the transport stays behind it.
    """
    recorded = Bundle.read(bundle) if isinstance(bundle, Path) else bundle
    storage_paths = {
        resource.name: upload_bytes(
            client,
            recorded.resource_bytes(resource),
            hash_=resource.hash,
            content_type=content_type_for(resource.type),
        )
        for resource in _managed(recorded)
    }
    return client.replay_bundle(_request(recorded, storage_paths))


async def send_bundle_async(
    client: BookshelfClient,
    bundle: Path | Bundle,
) -> models.BundleReplayResponse:
    """Asynchronous counterpart to :func:`send_bundle`."""
    recorded = Bundle.read(bundle) if isinstance(bundle, Path) else bundle
    storage_paths = {
        resource.name: await upload_bytes_async(
            client,
            recorded.resource_bytes(resource),
            hash_=resource.hash,
            content_type=content_type_for(resource.type),
        )
        for resource in _managed(recorded)
    }
    return await client.replay_bundle_async(_request(recorded, storage_paths))


async def replay_bundle(
    bundle: Path | Bundle,
    bs: AsyncBookshelf,
) -> models.BundleReplayResponse:
    """Replay a recorded bundle through an asynchronous Bookshelf client.

    Pass a :class:`pathlib.Path` for the usual publish workflow.
    The path must name a bundle directory containing its manifest and recorded resource bytes.
    Pass an already loaded :class:`Bundle`
    when the caller needs to inspect, validate, or transport the bundle before replay.

    The managed bytes are uploaded first,
    then the whole bundle is sent as one request.
    The server computes the seal from that request,
    so replaying the same bundle twice converges on one edition
    and the second run reports ``converged``.
    If the manifest marks the book as published, the same request publishes it.

    Args:
        bundle: Bundle directory or an already loaded bundle.
        bs: Open asynchronous client used for the upload and the replay.

    Returns:
        What the replay resolved to, the resulting book among it.

    Raises:
        ValueError: The bundle contains an invalid resource representation.
    """
    return await bs.replay_bundle(bundle)


def replay_bundle_sync(
    bundle: Path | Bundle,
    bs: Bookshelf,
) -> models.BundleReplayResponse:
    """Replay a recorded bundle through a synchronous Bookshelf client.

    This is the synchronous counterpart to :func:`replay_bundle`.
    It accepts the same path or loaded bundle forms,
    and it converges the same way.
    """
    return bs.replay_bundle(bundle)


__all__ = ["replay_bundle", "replay_bundle_sync"]
