"""Minimal valid wire payloads for the transport core tests, shared across test modules."""

import json
from typing import Any

from bookshelf._core.types import ApiResponse

TS = "2026-01-01T00:00:00Z"

BOOK_DETAIL: dict[str, Any] = {
    "book_id": "0197a000-0000-7000-8000-0000000000b1",
    "version": "1.0.0",
    "edition": 1,
    "status": "draft",
    "visibility": "hidden",
    "created_at": TS,
    "series_name": "primap-hist",
}

BOOK_RESPONSE: dict[str, Any] = {
    "id": "b1",
    "volume_id": "v1",
    "owner_org_id": "org_1",
    "version": "1.0.0",
    "edition": 1,
    "description": None,
    "status": "draft",
    "visibility": "hidden",
    "private": True,
    "metadata": {},
    "hash": None,
    "created_at": TS,
    "updated_at": TS,
    "published_at": None,
}

BOOK_LIST: dict[str, Any] = {
    "items": [],
    "total": 0,
    "limit": 50,
    "offset": 0,
    "has_more": False,
}

BOOK_ENTRIES: dict[str, Any] = {"items": []}


def book_list_item(*, status: str = "draft", edition: int = 1) -> dict[str, Any]:
    """One book list row, which the address-resolving callers need to have something to find."""
    return {
        "id": "b1",
        "volume_name": "example",
        "version": "v1.0.0",
        "edition": edition,
        "status": status,
        "visibility": "hidden",
        "private": True,
        "metadata": {},
        "created_at": TS,
        "published_at": TS if status == "published" else None,
    }


VOLUME: dict[str, Any] = {
    "id": "vol_1",
    "name": "example",
    "owner_org_id": "org_1",
    "description": None,
    "license": "MIT",
    "metadata": {},
    "authors": [],
    "maintainers": [],
    "created_at": TS,
    "updated_at": TS,
}

ENTRY_ATTACHED: dict[str, Any] = {
    "entry_id": "0197a000-0000-7000-8000-0000000000e1",
    "book_id": "0197a000-0000-7000-8000-0000000000b1",
    "tracking_id": "0197a000-0000-7000-8000-000000000001",
    "name_in_book": "by_country",
}

DOWNLOAD: dict[str, Any] = {"presigned_url": "https://s3.example/key?sig=abc", "expires_in": 900}

INVALIDATED: dict[str, Any] = {
    "tracking_id": "0197a000-0000-7000-8000-000000000001",
    "reason": "bad units",
    "invalidated_at": TS,
}

RESOURCE_READ: dict[str, Any] = {
    "tracking_id": "0197a000-0000-7000-8000-000000000001",
    "type": "timeseries",
    "hash": "sha256:" + "0" * 64,
    "visibility": "org",
    "owner_org_id": "org_1",
    "created_at": TS,
    "updated_at": TS,
}

RESOURCE_LIST: dict[str, Any] = {"items": []}

RESOURCE_EVENTS: dict[str, Any] = {"items": []}

REGISTERED: dict[str, Any] = {"activity_created": False, "atomic": True, "registered": []}

UPLOAD_INITIATED: dict[str, Any] = {
    "upload_id": "u1",
    "storage_path": "ingest/org_1/abc",
    "parts": [
        {
            "part_number": 1,
            "presigned_url": "https://s3.example/part1?sig=abc",
            "start_byte": 0,
            "end_byte": 9,
        }
    ],
}

UPLOAD_EXISTS: dict[str, Any] = {"already_exists": True, "storage_path": "ingest/org_1/abc"}


def problem(status: int, title: str, detail: str) -> dict[str, Any]:
    """One problem+json body, so a fixture does not claim a status its title contradicts."""
    return {
        "type": f"https://bookshelf.example/problems/{status}",
        "title": title,
        "status": status,
        "detail": detail,
    }


PROBLEM_CONFLICT: dict[str, Any] = {
    "type": "https://bookshelf.example/problems/conflict",
    "title": "Conflict",
    "status": 409,
    "detail": "logical_key already registered with a different hash",
}


def json_response(
    status_code: int,
    payload: Any,
    *,
    media_type: str = "application/json",
    headers: dict[str, str] | None = None,
) -> ApiResponse:
    return ApiResponse(
        status_code=status_code,
        headers={"content-type": media_type, **(headers or {})},
        content=json.dumps(payload).encode(),
    )


def empty_response(status_code: int, headers: dict[str, str] | None = None) -> ApiResponse:
    return ApiResponse(status_code=status_code, headers=headers or {}, content=b"")
