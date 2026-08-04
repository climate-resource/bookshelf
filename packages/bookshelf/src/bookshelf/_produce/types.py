"""Public value types for producing Bookshelf resources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.visibility import INHERIT, VisibilityInput

if TYPE_CHECKING:
    from bookshelf._produce.resources import AsyncResource, Resource


@dataclass(frozen=True, slots=True)
class Used:
    """Resolve a resource input by its producer-supplied logical key."""

    logical_key: str

    def __post_init__(self) -> None:
        if not self.logical_key:
            raise ValueError("logical_key must not be empty")


@dataclass(frozen=True, slots=True)
class RegisterItem:
    """One managed object to materialise as part of an activity batch.

    With the default ``dedupe=True``,
    byte-identical objects owned by the same organisation
    collapse to one canonical resource,
    even when their logical keys differ.
    The first resource's logical key remains canonical.
    """

    obj: object
    type: str | models.ResourceType
    logical_key: str | None = None
    visibility: VisibilityInput = INHERIT
    tags: Sequence[str] = ()
    metadata: Mapping[str, Any] | None = None
    tracking_id: UUID | None = None
    format: str | None = None
    dedupe: bool = True


class HasTrackingId(Protocol):
    """Object exposing a resource tracking id."""

    tracking_id: UUID


UsedInput = Used | HasTrackingId | str | UUID


@dataclass(frozen=True, slots=True)
class RegistrationSuccess:
    """One successful item from a possibly partial registration batch."""

    index: int
    outcome: models.RegistrationOutcome


@dataclass(frozen=True, slots=True)
class RegistrationFailure:
    """One failed item from a non-atomic registration response."""

    index: int
    error: models.ItemError


class PartialRegistrationError(BookshelfError):
    """A non-atomic batch committed some items and rejected others."""

    def __init__(
        self,
        *,
        successful: Sequence[RegistrationSuccess],
        failures: Sequence[RegistrationFailure],
    ) -> None:
        self.successful = tuple(successful)
        self.failures = tuple(failures)
        self.successful_resources: tuple[Resource | AsyncResource, ...] = ()
        failed = ", ".join(str(failure.index) for failure in failures)
        super().__init__(f"registration batch partially failed at indices: {failed}")

    @property
    def successful_outcomes(self) -> tuple[models.RegistrationOutcome, ...]:
        """Return every outcome whose resource was committed."""
        return tuple(success.outcome for success in self.successful)

    @property
    def failed_indices(self) -> tuple[int, ...]:
        """Return item indices, preserving the server's ``-1`` lineage sentinel."""
        return tuple(failure.index for failure in self.failures)


__all__ = [
    "HasTrackingId",
    "PartialRegistrationError",
    "RegisterItem",
    "RegistrationFailure",
    "RegistrationSuccess",
    "Used",
    "UsedInput",
]
