"""A mocked platform serving one volume of timeseries books, shared by the read tests."""

import hashlib
import io
import re
from typing import Any

import httpx
import pandas as pd

from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"
TRACKING_ID = payloads.RESOURCE_READ["tracking_id"]
BOOK_ID = payloads.BOOK_DETAIL["book_id"]

WIDE = pd.DataFrame(
    {
        "model": ["m"] * 3,
        "region": ["NZL", "NZL", "AUS"],
        "scenario": ["s"] * 3,
        "unit": ["Mt CO2/yr", "Mt CH4/yr", "Mt CO2/yr"],
        "variable": ["Emissions|CO2", "Emissions|CH4", "Emissions|CO2"],
        "2000-01-01": [1.0, 2.0, 3.0],
        "2001-01-01 00:00:00": [1.5, 2.5, 3.5],
    }
)


def _parquet(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    return buffer.getvalue()


def _books(versions: list[tuple[str, int]]) -> dict[str, Any]:
    items = [
        dict(
            payloads.book_list_item(status="published"),
            id=BOOK_ID,
            volume_name="primap-hist",
            version=v,
            edition=e,
        )
        for v, e in versions
    ]
    return dict(payloads.BOOK_LIST, items=items, total=len(items))


def _volume(versions: list[tuple[str, int]]) -> dict[str, Any]:
    """The volume summary that lists the published versions."""
    editions: dict[str, list[dict[str, Any]]] = {}
    for version, edition in versions:
        editions.setdefault(version, []).append(
            {
                "edition": edition,
                "status": "published",
                "created_at": payloads.TS,
                "published_at": payloads.TS,
            }
        )
    return dict(
        payloads.VOLUME,
        name="primap-hist",
        versions=[{"version": version, "editions": found} for version, found in editions.items()],
        stats={
            "total_versions": len(editions),
            "total_editions": len(versions),
            "total_resources": len(versions),
            "total_size_bytes": 0,
        },
    )


def _entries(*names: str) -> dict[str, Any]:
    return {
        "items": [
            dict(payloads.ENTRY_ATTACHED, name_in_book=name, type="timeseries", visibility="public")
            for name in names
        ],
        "next_cursor": None,
    }


def _platform(
    versions: list[tuple[str, int]],
    *,
    entries: tuple[str, ...] = ("by_country",),
    frame: pd.DataFrame = WIDE,
    external: bool = False,
) -> httpx.MockTransport:
    """A volume holding ``versions``, every book sharing one timeseries entry.

    An ``external`` entry is a pointer the platform reads in place, so only ``/data`` serves it.
    """
    content = _parquet(frame)
    resource = dict(payloads.RESOURCE_READ, hash=f"sha256:{hashlib.sha256(content).hexdigest()}")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "s3.example":
            return httpx.Response(200, content=content)
        if path == "/v1/volumes/primap-hist":
            return httpx.Response(200, json=_volume(versions))
        if path.startswith("/v1/volumes/"):
            return httpx.Response(404, json={"detail": "no such volume"})
        if path == "/v1/books":
            params = request.url.params
            if params.get("volume") != "primap-hist":
                return httpx.Response(404, json={"detail": "no such volume"})
            wanted = params.get("version")
            chosen = [(v, e) for v, e in versions if wanted is None or v == wanted]
            return httpx.Response(200, json=_books(chosen))
        if re.fullmatch(r"/v1/books/[^/]+/entries", path):
            return httpx.Response(200, json=_entries(*entries))
        if path == f"/v1/resources/{TRACKING_ID}/download":
            if external:
                return httpx.Response(
                    200, json={"presigned_url": "s3://elsewhere/by_country", "expires_in": 900}
                )
            return httpx.Response(200, json=payloads.DOWNLOAD)
        if external and path == f"/v1/resources/{TRACKING_ID}/data":
            return httpx.Response(
                200, content=content, headers={"content-type": "application/parquet"}
            )
        if path == f"/v1/resources/{TRACKING_ID}":
            return httpx.Response(200, json=resource)
        return httpx.Response(404, json={"detail": f"unhandled {path}"})

    return httpx.MockTransport(handler)
