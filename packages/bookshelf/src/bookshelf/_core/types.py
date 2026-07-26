"""Request/response value types for the transport core.

``build_*`` functions produce an :class:`ApiRequest` without touching a socket.
The client shells turn it into an httpx request, and hand the wire result back
as an :class:`ApiResponse` for the matching ``parse_*`` function.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

DataFormat = Literal["json", "csv", "parquet"]

ACCEPT_BY_FORMAT: dict[DataFormat, str] = {
    "json": "application/json",
    "csv": "text/csv",
    "parquet": "application/parquet",
}

FORMAT_BY_MEDIA_TYPE: dict[str, DataFormat] = {
    media_type: fmt for fmt, media_type in ACCEPT_BY_FORMAT.items()
}


@dataclass(frozen=True, slots=True)
class ApiRequest:
    """A fully described HTTP request, independent of any transport.

    ``path`` is relative to the client base URL unless ``absolute_url`` is set
    (the presigned-PUT case, which targets object storage directly).
    """

    method: str
    path: str
    params: dict[str, str | int | bool | list[str]] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    json_body: Any | None = None
    form_body: dict[str, str] | None = None
    content: bytes | None = None
    absolute_url: str | None = None


@dataclass(frozen=True, slots=True)
class ApiResponse:
    """The transport-independent result of executing an :class:`ApiRequest`."""

    status_code: int
    headers: dict[str, str]
    content: bytes

    @property
    def media_type(self) -> str:
        content_type = self.headers.get("content-type", "")
        return content_type.split(";")[0].strip().lower()


@dataclass(frozen=True, slots=True)
class DataPayload:
    """Raw ``/data`` bytes plus the negotiated format, ready for frame conversion."""

    format: DataFormat
    content: bytes
    etag: str | None = None


@dataclass(frozen=True, slots=True)
class NotModified:
    """``/data`` conditional-request outcome: the caller's ETag is still current."""

    etag: str | None = None
