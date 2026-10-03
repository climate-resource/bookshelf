"""SDK-owned value types for what the public API returns.

The generated models track the platform contract and change whenever it does.
These types are the promise, and the converters here are the only place the two meet.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, RootModel

from bookshelf._generated import models


class _OpenStrEnum(StrEnum):
    """A string enum that keeps a value this SDK does not know, rather than refusing it."""

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        if not isinstance(value, str):
            return None
        member = str.__new__(cls, value)
        member._name_ = value.upper()
        member._value_ = value
        return member


class ResourceType(_OpenStrEnum):
    """The kind of data a resource holds, which decides the reads it answers.

    A type a newer platform adds arrives as a member of its own,
    so the resource stays readable as bytes rather than failing to load.
    """

    TIMESERIES = "timeseries"
    TABULAR = "tabular"
    GEOSPATIAL = "geospatial"
    DOCUMENT = "document"
    BINARY = "binary"
    FIGURE = "figure"


class Visibility(_OpenStrEnum):
    """Who can read a book or resource.

    A tier a newer platform adds arrives as a member of its own rather than an error.
    """

    HIDDEN = "hidden"
    ORG = "org"
    PUBLIC = "public"


def known_member[E: StrEnum](enum: type[E], value: str) -> E:
    """Look up a value a caller supplied, refusing one the enum does not list."""
    member = enum._value2member_map_.get(value)
    if not isinstance(member, enum):
        allowed = ", ".join(enum._value2member_map_)
        raise ValueError(f"{value!r} is not a valid {enum.__name__}, use one of: {allowed}")
    return member


@dataclass(frozen=True, slots=True)
class Identity:
    """Who the API accepted a credential as."""

    id: str
    email: str
    first_name: str | None
    last_name: str | None
    organization_id: str | None
    role: str | None
    permissions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VolumeSummary:
    """One volume in a search result, with enough to decide whether to open it."""

    name: str
    title: str | None
    description: str | None
    license: str | None
    latest_version: str | None
    latest_edition: int | None
    resource_types: tuple[ResourceType, ...]
    formats: tuple[str, ...]
    total_resources: int
    total_size_bytes: int
    deprecated: bool
    discovery: Mapping[str, Any]
    """The volume's whole discovery profile, as JSON-compatible values."""


@dataclass(frozen=True, slots=True)
class VolumeSearchResults:
    """One page of the volumes matching a search.

    Read ``has_more`` rather than comparing counts, and page with ``offset``.
    """

    items: tuple[VolumeSummary, ...]
    total: int
    limit: int
    offset: int
    has_more: bool

    def __iter__(self) -> Iterator[VolumeSummary]:
        """Iterate over the volumes on this page."""
        return iter(self.items)


@dataclass(frozen=True, slots=True)
class FacetValue:
    """One distinct value of a column, and how many series use it."""

    value: Any
    count: int


@dataclass(frozen=True, slots=True)
class Facet:
    """One index column and its distinct values."""

    column: str
    values: tuple[FacetValue, ...]
    total_unique: int
    """How many distinct values the whole entry holds, which ``values`` may truncate."""
    truncated: bool


@dataclass(frozen=True, slots=True)
class Facets:
    """The index columns of an entry and the distinct values each one holds."""

    facets: tuple[Facet, ...]
    categorical_columns: tuple[str, ...]
    numeric_columns: tuple[str, ...]
    total_rows: int

    def __getitem__(self, column: str) -> Facet:
        """Look up one column's facet, raising KeyError for a column the entry does not index."""
        for facet in self.facets:
            if facet.column == column:
                return facet
        raise KeyError(column)


@dataclass(frozen=True, slots=True)
class SeriesMetadata:
    """One page of an entry's series, each described by its index values alone."""

    index: tuple[Mapping[str, Any], ...]
    columns: tuple[str, ...]
    total_rows: int
    limit: int
    offset: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class Problem:
    """The RFC 9457 problem document an API error response carried."""

    type: str
    title: str
    status: int
    detail: str
    instance: str | None
    errors: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ItemError:
    """One item a non-atomic batch request rejected."""

    status: int
    detail: str


@dataclass(frozen=True, slots=True)
class BookCorrection:
    """What a correction to a published book changed."""

    book_id: UUID
    corrected: tuple[str, ...]
    """The fields the correction changed, empty when it changed nothing."""
    corrected_at: datetime
    discovery: Mapping[str, Any]
    """The book's discovery profile after the correction."""
    metadata: Mapping[str, Any]
    """The book's metadata after the correction."""


def json_fields(model: BaseModel | None) -> dict[str, Any]:
    """Flatten a generated model into JSON-compatible values, leaving out what it does not state."""
    if model is None:
        return {}
    return model.model_dump(mode="json", exclude_none=True)


def discovery_text(discovery: BaseModel | None, field: str) -> str | None:
    """Unwrap one constrained string from a discovery profile that may be absent."""
    value: RootModel[str] | None = getattr(discovery, field, None)
    return None if value is None else value.root


def resource_type(value: StrEnum) -> ResourceType:
    return ResourceType(value.value)


def visibility(value: StrEnum) -> Visibility:
    return Visibility(value.value)


def identity(user: models.UserResponse) -> Identity:
    return Identity(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        organization_id=user.organization_id,
        role=user.role,
        permissions=tuple(user.permissions or ()),
    )


def volume_summary(item: models.VolumeListItem) -> VolumeSummary:
    discovery = item.discovery
    return VolumeSummary(
        name=item.name,
        title=discovery_text(discovery, "title"),
        description=discovery_text(discovery, "description"),
        license=discovery_text(discovery, "license"),
        latest_version=item.latest_version,
        latest_edition=item.latest_edition,
        resource_types=tuple(ResourceType(value) for value in item.resource_types or ()),
        formats=tuple(item.formats or ()),
        total_resources=item.total_resources or 0,
        total_size_bytes=item.total_size_bytes or 0,
        deprecated=bool(discovery and discovery.deprecated),
        discovery=json_fields(discovery),
    )


def search_results(response: models.VolumeListResponse) -> VolumeSearchResults:
    return VolumeSearchResults(
        items=tuple(volume_summary(item) for item in response.items),
        total=response.total,
        limit=response.limit,
        offset=response.offset,
        has_more=response.has_more,
    )


def facets(response: models.FacetsResponse) -> Facets:
    return Facets(
        facets=tuple(
            Facet(
                column=facet.column,
                values=tuple(
                    FacetValue(value=value.value, count=value.count) for value in facet.values
                ),
                total_unique=facet.total_unique,
                truncated=bool(facet.truncated),
            )
            for facet in response.facets
        ),
        categorical_columns=tuple(response.categorical_columns),
        numeric_columns=tuple(response.numeric_columns),
        total_rows=response.total_rows,
    )


def series_metadata(response: models.TimeseriesMetadataResponse) -> SeriesMetadata:
    return SeriesMetadata(
        index=tuple(response.index),
        columns=tuple(response.columns),
        total_rows=response.total_rows,
        limit=response.limit,
        offset=response.offset,
        has_more=response.has_more,
    )


def problem(document: models.Problem) -> Problem:
    return Problem(
        type=document.type,
        title=document.title,
        status=document.status,
        detail=document.detail,
        instance=document.instance,
        errors=tuple(document.errors or ()),
    )


def book_correction(response: models.BookCorrectionResponse) -> BookCorrection:
    return BookCorrection(
        book_id=response.book_id,
        corrected=tuple(response.corrected or ()),
        corrected_at=response.corrected_at,
        discovery=json_fields(response.discovery),
        metadata=dict(response.metadata),
    )


__all__ = [
    "BookCorrection",
    "Facet",
    "FacetValue",
    "Facets",
    "Identity",
    "ItemError",
    "Problem",
    "ResourceType",
    "SeriesMetadata",
    "Visibility",
    "VolumeSearchResults",
    "VolumeSummary",
    "known_member",
]
