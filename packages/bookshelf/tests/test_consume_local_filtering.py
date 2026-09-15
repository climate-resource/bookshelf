"""Converters read the whole resource and filter locally, and ``query()`` filters on the server."""

from pathlib import Path

import httpx
import pandas as pd
import pytest

from bookshelf import AsyncBookshelf, Bookshelf
from bookshelf._consume.frames import filter_rows, filter_years
from bookshelf._core.errors import BookshelfError
from bookshelf.cache import ContentCache
from tests.test_legacy import BASE_URL, TRACKING_ID, _platform


def _requests(transport: httpx.MockTransport) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    inner = transport.handler

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return inner(request)  # type: ignore[return-value]

    return httpx.MockTransport(handler), seen


def _shelf(tmp_path: Path) -> tuple[Bookshelf, list[httpx.Request]]:
    transport, seen = _requests(_platform([("v2.6", 1)]))
    bs = Bookshelf(BASE_URL, auth=None, transport=transport)
    bs._cache = ContentCache(tmp_path / "cache")
    return bs, seen


def test_book_entry_as_df_reads_the_whole_file(tmp_path: Path) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    assert entry.as_df().equals(entry.as_resource().as_df())
    data = [request for request in seen if request.url.path.endswith("/data")]
    assert data and all(not request.url.params for request in data)
    assert not any("timeseries" in request.url.path for request in seen)


def test_filters_and_the_year_window_apply_locally(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    frame = entry.as_df(region="NZL", year_min=2001)

    assert list(frame.columns) == ["2001"]
    assert frame.index.get_level_values("region").unique().tolist() == ["NZL"]
    assert len(frame) == 2
    long = entry.as_long_df(variable="Emissions|CO2", year_max=2000)
    assert long["year"].tolist() == [2000, 2000]


def test_an_unknown_filter_column_is_rejected(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)
    with pytest.raises(KeyError, match="regoin"):
        bs.resource(TRACKING_ID).as_df(regoin="NZL")


async def test_the_async_entry_reads_the_whole_file(tmp_path: Path) -> None:
    transport, seen = _requests(_platform([("v2.6", 1)]))
    async with AsyncBookshelf(BASE_URL, auth=None, async_transport=transport) as bs:
        bs._cache = ContentCache(tmp_path / "cache")
        book = await bs.book("primap-hist", "v2.6")
        frame = await book["by_country"].as_df(region="AUS")

    assert len(frame) == 1
    assert not any("timeseries" in request.url.path for request in seen)


def test_query_sends_the_trimming_to_the_book_endpoint(tmp_path: Path) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    # The fixture platform has no timeseries route, so only the request matters here.
    with pytest.raises(BookshelfError):
        entry.query(region="NZL", year_min=2001, top_n=1)

    (request,) = [request for request in seen if "timeseries" in request.url.path]
    assert request.url.params["region"] == "NZL"
    assert request.url.params["year.min"] == "2001"
    assert request.url.params["top_n"] == "1"


def test_filter_rows_compares_as_strings() -> None:
    frame = pd.DataFrame({"category": [1, 2, 1], "value": [1.0, 2.0, 3.0]})
    assert filter_rows(frame, {"category": "1"})["value"].tolist() == [1.0, 3.0]


def test_filter_years_keeps_the_inclusive_window() -> None:
    wide = pd.DataFrame([[1.0, 2.0, 3.0]], columns=["2000", "2001", "2002"])
    assert list(filter_years(wide, year_min=2001, year_max=2002).columns) == ["2001", "2002"]
    assert filter_years(wide, year_min=None, year_max=None) is wide
