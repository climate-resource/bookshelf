"""Pydantic schemas for API request/response validation.

Uses pydantic v1 syntax to match existing bookshelf codebase.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field


# Enums
class BookStatus(str, Enum):
    """Book lifecycle status."""

    DRAFT = "draft"
    PUBLISHED = "published"


class ResourceType(str, Enum):
    """Type of resource data."""

    TIMESERIES = "timeseries"
    GEOSPATIAL = "geospatial"
    TABULAR = "tabular"
    DOCUMENT = "document"
    BINARY = "binary"


class Scope(str, Enum):
    """API key permission scopes."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


# Auth schemas
class TokenResponse(BaseModel):
    """OAuth2 token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Token lifetime in seconds")


# Pagination
T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: list[T]
    total: int = Field(..., description="Total number of items matching the query")
    limit: int = Field(..., description="Maximum items per page")
    offset: int = Field(..., description="Number of items skipped")
    has_more: bool = Field(..., description="Whether more items exist")


# Book schemas
class DataDictionaryEntry(BaseModel):
    """Schema for data dictionary entries."""

    name: str = Field(..., description="Column/field name")
    type: str = Field(..., description="Data type (e.g., 'string', 'float', 'datetime')")
    description: Optional[str] = Field(None, description="Field description")
    unit: Optional[str] = Field(None, description="Unit of measurement")
    required: bool = Field(True, description="Whether field is required")


class ResourceSummary(BaseModel):
    """Minimal resource info for book responses."""

    id: str
    name: str
    type: str
    format: str
    size_bytes: int


class BookResponse(BaseModel):
    """Full book response."""

    id: str
    volume_id: str
    version: str
    edition: int
    description: Optional[str]
    status: BookStatus
    private: bool
    metadata: dict[str, Any]
    data_dictionary: list[DataDictionaryEntry]
    hash: Optional[str]
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime]
    resources: list[ResourceSummary] = Field(default_factory=list)

    @property
    def edition_string(self) -> str:
        """Format edition as e001, e002, etc."""
        return f"e{self.edition:03}"


class BookListItem(BaseModel):
    """Book response for list endpoints."""

    id: str
    version: str
    edition: int
    status: BookStatus
    private: bool
    created_at: datetime
    published_at: Optional[datetime]
    resource_count: int = 0


class BookListResponse(BaseModel):
    """Paginated book list response."""

    items: list[BookListItem]
    total: int = Field(..., description="Total number of items matching the query")
    limit: int = Field(..., description="Maximum items per page")
    offset: int = Field(..., description="Number of items skipped")
    has_more: bool = Field(..., description="Whether more items exist")


# Volume schemas
class VolumeResponse(BaseModel):
    """Full volume response."""

    id: str
    name: str
    description: Optional[str]
    license: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VolumeListItem(BaseModel):
    """Volume response for list endpoints with aggregated fields."""

    id: str
    name: str
    description: Optional[str]
    license: str
    created_at: datetime
    updated_at: datetime
    latest_version: Optional[str] = Field(None, description="Most recent version string")
    latest_edition: Optional[int] = Field(None, description="Highest edition for latest_version")
    resource_types: list[str] = Field(default_factory=list, description="Unique resource types")


class EditionInfo(BaseModel):
    """Edition information within a version."""

    edition: int
    status: str
    created_at: datetime
    published_at: Optional[datetime]


class VersionInfo(BaseModel):
    """Version information within a volume."""

    version: str
    editions: list[EditionInfo]


class VolumeStats(BaseModel):
    """Statistics for a volume."""

    total_versions: int
    total_editions: int
    total_resources: int
    total_size_bytes: int


class VolumeDetailResponse(VolumeResponse):
    """Detailed volume response with versions and stats."""

    versions: list[VersionInfo]
    stats: VolumeStats


class VolumeListResponse(BaseModel):
    """Paginated volume list response."""

    items: list[VolumeListItem]
    total: int = Field(..., description="Total number of items matching the query")
    limit: int = Field(..., description="Maximum items per page")
    offset: int = Field(..., description="Number of items skipped")
    has_more: bool = Field(..., description="Whether more items exist")
