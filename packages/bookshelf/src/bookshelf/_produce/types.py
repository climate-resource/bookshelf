"""Public value types for producing Bookshelf resources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from bookshelf._core.errors import BookshelfError
from bookshelf._core.names import validate_resource_name
from bookshelf._generated import models
from bookshelf._produce.visibility import INHERIT, VisibilityInput

if TYPE_CHECKING:
    from bookshelf._produce.resources import AsyncResource, Resource


type AuthorInput = models.Author | Mapping[str, Any]
"""One credited person, as a model or as the mapping a recipe dumps them to."""


@dataclass(frozen=True, slots=True)
class Used:
    """Resolve a resource input by the name it was registered under.

    Resolution is confined to the resources registered by the same request.
    A resource produced by an earlier build is referenced by its tracking id instead.
    """

    name: str

    def __post_init__(self) -> None:
        validate_resource_name(self.name)


@dataclass(frozen=True, slots=True)
class RegisterItem:
    """One managed object to materialise as part of an activity batch.

    With the default ``dedupe=True``,
    byte-identical objects owned by the same organisation
    collapse to one canonical resource,
    even when their names differ.
    The first resource's name remains canonical.
    """

    obj: object
    type: str | models.ResourceType
    name: str | None = None
    visibility: VisibilityInput = INHERIT
    tags: Sequence[str] = ()
    description: str | None = None
    authors: Sequence[AuthorInput] | None = None
    doi: str | None = None
    citation: str | None = None
    license: str | None = None
    license_url: str | None = None
    metadata: Mapping[str, Any] | None = None
    tracking_id: UUID | None = None
    format: str | None = None
    dedupe: bool = True

    def __post_init__(self) -> None:
        if self.name is not None:
            validate_resource_name(self.name)


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
    "AuthorInput",
    "HasTrackingId",
    "PartialRegistrationError",
    "RegisterItem",
    "RegistrationFailure",
    "RegistrationSuccess",
    "Used",
    "UsedInput",
]
