"""Shared helpers for synchronous and asynchronous production."""

from __future__ import annotations

import os
import platform
import secrets
import time
from collections.abc import Mapping, Sequence
from uuid import UUID

from bookshelf._generated import models
from bookshelf._produce.provenance import canonical_config_hash
from bookshelf._produce.types import (
    PartialRegistrationError,
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


def registered_tracking_id(outcome: models.RegistrationOutcome) -> UUID:
    """Return the canonical id while preserving the original outcome."""
    return outcome.aliased_to or outcome.tracking_id


def registered_resource_type(
    outcome: models.RegistrationOutcome,
    requested: models.ResourceType,
) -> models.ResourceType | None:
    """Return a trusted local type, or defer canonical alias metadata loading."""
    if outcome.status is models.Status1.aliased:
        return None
    return requested


def used_ref(value: UsedInput) -> models.UsedRefByTrackingId | models.UsedRefByLogicalKey:
    """Convert a public lineage input into its wire representation."""
    if isinstance(value, Used):
        return models.UsedRefByLogicalKey(logical_key=value.logical_key)
    if isinstance(value, str | UUID):
        try:
            tracking_id = UUID(str(value))
        except ValueError as exc:
            raise ValueError(
                "a bare string in used= is always a tracking id. "
                "Use Used(logical_key=...) for logical key resolution"
            ) from exc
        return models.UsedRefByTrackingId(tracking_id=tracking_id)
    handle_tracking_id = getattr(value, "tracking_id", None)
    if handle_tracking_id is None:
        raise TypeError(
            "used entries must be a BookEntry, Resource, prior register output, "
            "tracking id, or Used(logical_key=...)"
        )
    return models.UsedRefByTrackingId(tracking_id=UUID(str(handle_tracking_id)))


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


def raise_partial_registration(
    successful: Sequence[RegistrationSuccess],
    failures: Sequence[RegistrationFailure],
) -> None:
    """Raise the aggregate error only after retaining every response item."""
    if failures:
        raise PartialRegistrationError(successful=successful, failures=failures)


__all__ = [
    "INHERIT",
    "MAX_REGISTRATION_BATCH",
    "VisibilityInput",
    "activity_envelope",
    "raise_partial_registration",
    "registered_resource_type",
    "registered_tracking_id",
    "registration_results",
    "resource_type",
    "runner",
    "uuid7",
    "visibility",
]
