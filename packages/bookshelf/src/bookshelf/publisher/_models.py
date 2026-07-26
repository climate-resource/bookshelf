"""Hand-written wire shapes shared by the recipe and notebook publisher modules.

These mirror the API request shapes rather than reusing the generated models,
because the recipe file is authored by hand
and its fields are validated against a stricter ``extra="forbid"`` contract.
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Visibility = Literal["hidden", "org", "public"]
ResourceType = Literal["timeseries", "geospatial", "tabular", "document", "binary"]


class LocationInput(BaseModel):
    """A ``(shelf, path)`` pair attached to a registration."""

    model_config = ConfigDict(extra="forbid")

    shelf: str
    path: str


class RegisterResourceItem(BaseModel):
    """One resource registration item posted to ``POST /v1/resources/registrations``.

    External pointers are detected from a non-null ``external_uri``.
    Managed (S3-backed) registrations leave it null and supply a ``hash``.
    """

    model_config = ConfigDict(extra="forbid")

    tracking_id: UUID | None = None
    type: ResourceType
    hash: str | None = None
    format: str | None = None
    logical_key: str | None = None
    visibility: Visibility = "hidden"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    external_uri: str | None = None
    locations: list[LocationInput] = Field(default_factory=list)
    dedupe: bool = True
    """When ``True`` by default,
    the server aliases to an existing resource
    that shares the content hash.
    Set ``False`` for per-book entry resources,
    including outputs and notebooks.
    Each edition then owns a distinct resource row,
    even when the bytes are identical.
    """


class Author(BaseModel):
    """An author or maintainer attributed on a volume."""

    model_config = ConfigDict(extra="forbid")

    name: str
    email: str | None = None
    affiliation: str | None = None
    orcid: str | None = None


__all__ = [
    "Author",
    "LocationInput",
    "RegisterResourceItem",
    "ResourceType",
    "Visibility",
]
