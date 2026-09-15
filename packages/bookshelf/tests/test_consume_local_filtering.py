"""Converters read the whole resource and filter locally, and ``query()`` filters on the server."""

from pathlib import Path

import httpx
import pandas as pd
import pytest

from bookshelf import AsyncBookshelf, Bookshelf
from bookshelf._consume.frames import filter_rows, filter_years
from bookshelf._core.errors import BookshelfError
from bookshelf.cache import ContentCache
from tests.test_legacy import BASE_URL, TRACKING_ID, WIDE, _platform


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


def _empty_methane() -> pd.DataFrame:
    frame = WIDE.copy()
    frame.loc[frame["variable"] == "Emissions|CH4", ["2000-01-01", "2001-01-01 00:00:00"]] = float(
        "nan"
    )
    return frame


def test_as_scmrun_keeps_timeseries_with_no_values(tmp_path: Path) -> None:
    pytest.importorskip("scmdata")
    bs = Bookshelf(BASE_URL, auth=None, transport=_platform([("v2.6", 1)], frame=_empty_methane()))
    bs._cache = ContentCache(tmp_path / "cache")

    run = bs.book("primap-hist", "v2.6")["by_country"].as_scmrun()

    assert len(run) == 3
    assert run.filter(variable="Emissions|CH4").timeseries().isna().all(axis=None)


async def test_the_async_as_scmrun_keeps_timeseries_with_no_values(tmp_path: Path) -> None:
    pytest.importorskip("scmdata")
    transport = _platform([("v2.6", 1)], frame=_empty_methane())
    async with AsyncBookshelf(BASE_URL, auth=None, async_transport=transport) as bs:
        bs._cache = ContentCache(tmp_path / "cache")
        book = await bs.book("primap-hist", "v2.6")
        run = await book["by_country"].as_scmrun()

    assert len(run) == 3
    assert run.filter(variable="Emissions|CH4").timeseries().isna().all(axis=None)


def _duplicated_first_row() -> pd.DataFrame:
    return pd.concat([WIDE, WIDE.iloc[:1]], ignore_index=True)


def test_as_scmrun_rejects_duplicate_metadata(tmp_path: Path) -> None:
    errors = pytest.importorskip("scmdata.errors")
    transport = _platform([("v2.6", 1)], frame=_duplicated_first_row())
    bs = Bookshelf(BASE_URL, auth=None, transport=transport)
    bs._cache = ContentCache(tmp_path / "cache")

    with pytest.raises(errors.NonUniqueMetadataError):
        bs.book("primap-hist", "v2.6")["by_country"].as_scmrun()


async def test_the_async_as_scmrun_rejects_duplicate_metadata(tmp_path: Path) -> None:
    errors = pytest.importorskip("scmdata.errors")
    transport = _platform([("v2.6", 1)], frame=_duplicated_first_row())
    async with AsyncBookshelf(BASE_URL, auth=None, async_transport=transport) as bs:
        bs._cache = ContentCache(tmp_path / "cache")
        book = await bs.book("primap-hist", "v2.6")
        with pytest.raises(errors.NonUniqueMetadataError):
            await book["by_country"].as_scmrun()


def test_an_unknown_filter_column_is_rejected(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)
    with pytest.raises(KeyError, match="regoin"):
        bs.resource(TRACKING_ID).as_df(regoin="NZL")


@pytest.mark.parametrize("argument", ["limit", "top_n", "drop_constant", "select"])
def test_converters_refuse_query_arguments_before_downloading(
    tmp_path: Path, argument: str
) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]
    before = len(seen)

    with pytest.raises(TypeError, match="query"):
        entry.as_long_df(**{argument: "1"})

    assert not any(request.url.path.endswith("/data") for request in seen[before:])


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


@pytest.mark.parametrize("category", [[1, 2, 1], [1.0, 2.0, 1.0], ["1", "2", "1"]])
def test_filter_rows_matches_numbers_by_value(category: list[object]) -> None:
    frame = pd.DataFrame({"category": category, "value": [1.0, 2.0, 3.0]})
    assert filter_rows(frame, {"category": "1"})["value"].tolist() == [1.0, 3.0]
    assert filter_rows(frame, {"category": "x"}).empty


def test_filter_rows_handles_booleans_and_nullable_numbers() -> None:
    flags = pd.DataFrame({"flag": [True, False, True]})
    assert len(filter_rows(flags, {"flag": "True"})) == 2
    counts = pd.DataFrame({"count": pd.array([1, None, 1], dtype="Int64")})
    assert len(filter_rows(counts, {"count": "1"})) == 2


def test_filters_combine_with_and() -> None:
    frame = pd.DataFrame({"a": ["x", "x", "y"], "b": ["p", "q", "p"]})
    assert len(filter_rows(frame, {"a": "x", "b": "p"})) == 1


def test_filter_years_keeps_the_inclusive_window() -> None:
    wide = pd.DataFrame([[1.0, 2.0, 3.0]], columns=["2000", "2001", "2002"])
    assert list(filter_years(wide, year_min=2001, year_max=2002).columns) == ["2001", "2002"]
    assert filter_years(wide, year_min=None, year_max=None) is wide
