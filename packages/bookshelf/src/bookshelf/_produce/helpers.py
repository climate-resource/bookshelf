"""Shared helpers for synchronous and asynchronous production."""

from __future__ import annotations

import os
import platform
import secrets
import time
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.provenance import canonical_config_hash
from bookshelf._produce.types import (
    AuthorInput,
    PartialRegistrationError,
    RegisterItem,
    RegistrationFailure,
    RegistrationSuccess,
    Used,
    UsedInput,
)
from bookshelf._produce.visibility import INHERIT, VisibilityInput
from bookshelf._produce.visibility import resolve as resolve_visibility

MAX_REGISTRATION_BATCH = 1000


def uuid7() -> UUID:
    """Mint RFC 9562 UUIDv7 bits from milliseconds and random values.

    Values minted within one millisecond have no additional ordering guarantee.
    """
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (timestamp_ms << 80) | (0x7 << 76) | (random_a << 64) | (0b10 << 62) | random_b
    return UUID(int=value)


def runner() -> str:
    """Describe the current execution environment without background work."""
    if run_id := os.environ.get("GITHUB_RUN_ID"):
        return f"github-actions:{run_id}"
    if os.environ.get("CI"):
        return "ci"
    return platform.node() or "local"


def resource_type(value: str | models.ResourceType) -> models.ResourceType:
    """Normalise a public resource-type input."""
    return value if isinstance(value, models.ResourceType) else models.ResourceType(value)


def visibility(
    value: VisibilityInput,
    default: models.Visibility = models.Visibility.hidden,
) -> models.Visibility:
    """Normalise a public visibility input, resolving :data:`INHERIT` to ``default``."""
    return resolve_visibility(value, default)


def registered_resource_type(
    outcome: models.RegistrationOutcome,
    requested: models.ResourceType,
) -> models.ResourceType | None:
    """Return a trusted local type, or defer canonical alias metadata loading."""
    if outcome.status is models.Status2.aliased:
        return None
    return requested


def used_ref(value: UsedInput) -> models.UsedRefByTrackingId | models.UsedRefByResourceName:
    """Convert a public lineage input into its wire representation."""
    if isinstance(value, Used):
        return models.UsedRefByResourceName(resource_name=value.name)
    if isinstance(value, str | UUID):
        try:
            tracking_id = UUID(str(value))
        except ValueError as exc:
            raise ValueError(
                "a bare string in used= is always a tracking id. "
                "Use Used(name=...) to resolve against this request's own resources"
            ) from exc
        return models.UsedRefByTrackingId(tracking_id=tracking_id)
    handle_tracking_id = getattr(value, "tracking_id", None)
    if handle_tracking_id is None:
        raise TypeError(
            "used entries must be a BookEntry, Resource, prior register output, "
            "tracking id, or Used(name=...)"
        )
    return models.UsedRefByTrackingId(tracking_id=UUID(str(handle_tracking_id)))


def resource_discovery(
    tags: Sequence[str] = (),
    *,
    description: str | None = None,
    authors: Sequence[AuthorInput] | None = None,
    doi: str | None = None,
    citation: str | None = None,
    license: str | None = None,
    license_url: str | None = None,
) -> models.ResourceDiscovery:
    """Gather a resource's catalogue metadata into the discovery object it travels in.

    A resource states its own attribution and never inherits the book's,
    so a field nobody wrote stays unset.
    An empty call still gets an object rather than a null,
    because the field is not nullable on the wire.
    A profile that states nothing and an absent profile mean the same thing to the platform.
    """
    return models.ResourceDiscovery(
        tags=list(tags),
        description=description,
        authors=None if authors is None else people(authors),
        doi=doi,
        citation=citation,
        license=license,
        license_url=license_url,
    )


def people(values: Sequence[AuthorInput]) -> list[models.Author]:
    """Validate a list of authors or maintainers, which share one shape."""
    return [models.Author.model_validate(value) for value in values]


def item_discovery(entry: RegisterItem) -> models.ResourceDiscovery:
    """Read one batch entry's catalogue metadata into the object it travels in."""
    return resource_discovery(
        entry.tags,
        description=entry.description,
        authors=entry.authors,
        doi=entry.doi,
        citation=entry.citation,
        license=entry.license,
        license_url=entry.license_url,
    )


def external_item(
    *,
    type: str | models.ResourceType,
    uri: str,
    hash: str | None,
    name: str | None,
    visibility: models.Visibility,
    discovery: models.ResourceDiscovery,
    metadata: Mapping[str, Any] | None,
    tracking_id: UUID | None,
    dedupe: bool,
) -> models.RegisterResourceItem:
    """Build the single-item registration an external pointer becomes.

    ``visibility`` is already resolved, because each surface carries its own default.
    """
    return models.RegisterResourceItem(
        tracking_id=tracking_id or uuid7(),
        type=resource_type(type),
        hash=hash,
        name=name,
        visibility=visibility,
        discovery=discovery,
        metadata=dict(metadata or {}),
        external_uri=uri,
        dedupe=dedupe,
    )


def activity_envelope(
    *,
    activity_id: UUID,
    kind: str,
    code_ref: str,
    config: Mapping[str, object],
    runner: str,
    used: Sequence[UsedInput],
    config_hash: str | None = None,
) -> models.ActivityEnvelope:
    """Build the activity envelope shared by all registrations in a block."""
    parameters = dict(config)
    return models.ActivityEnvelope(
        activity_id=activity_id,
        kind=kind,
        code_ref=code_ref,
        config_hash=config_hash or canonical_config_hash(parameters),
        parameters=parameters,
        runner=runner,
        used=[used_ref(value) for value in used],
    )


def registration_results(
    response: models.RegisterResourcesResponse,
    *,
    index_offset: int = 0,
) -> tuple[list[RegistrationSuccess], list[RegistrationFailure]]:
    """Split a server batch response without discarding committed outcomes."""
    successful: list[RegistrationSuccess] = []
    failures: list[RegistrationFailure] = []
    for result in response.registered or []:
        index = result.index if result.index < 0 else result.index + index_offset
        if result.outcome is not None:
            successful.append(RegistrationSuccess(index=index, outcome=result.outcome))
            continue
        error = result.error or models.ItemError(status=422, detail="registration failed")
        failures.append(RegistrationFailure(index=index, error=error))
    return successful, failures


def paired_successes(
    successful: Sequence[RegistrationSuccess],
    items: Sequence[models.RegisterResourceItem],
) -> list[tuple[models.RegistrationOutcome, models.RegisterResourceItem]]:
    """Pair every committed outcome with the request item it registered.

    The server reports the index of each result,
    so a reordered response still resolves to the right item.
    """
    if len(successful) != len(items):
        raise BookshelfError(
            f"The server committed {len(successful)} registrations for {len(items)} items."
        )
    paired = []
    for position, success in enumerate(successful):
        index = success.index if 0 <= success.index < len(items) else position
        paired.append((success.outcome, items[index]))
    return paired


def single_success(successful: Sequence[RegistrationSuccess]) -> models.RegistrationOutcome:
    """Return the only committed outcome, refusing a response that registered nothing."""
    if not successful:
        raise BookshelfError("The server returned no registration outcome for the request.")
    return successful[0].outcome


def raise_partial_registration(
    successful: Sequence[RegistrationSuccess],
    failures: Sequence[RegistrationFailure],
) -> None:
    """Raise the aggregate error only after retaining every response item."""
    if failures:
        raise PartialRegistrationError(successful=successful, failures=failures)


def registered_name(item: models.RegisterResourceItem) -> str | None:
    """Return the bundle-local name an item registers under, unwrapped from its model."""
    return None if item.name is None else item.name.root


__all__ = [
    "INHERIT",
    "MAX_REGISTRATION_BATCH",
    "VisibilityInput",
    "activity_envelope",
    "external_item",
    "item_discovery",
    "paired_successes",
    "people",
    "raise_partial_registration",
    "registered_name",
    "registered_resource_type",
    "registration_results",
    "resource_discovery",
    "resource_type",
    "runner",
    "single_success",
    "uuid7",
    "visibility",
]
