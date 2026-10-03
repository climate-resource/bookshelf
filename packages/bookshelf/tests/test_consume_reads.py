"""Every read takes one selection, and gives the same answer from the cached file or the platform."""

import re
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest

from bookshelf import (
    AsyncBookshelf,
    Bookshelf,
    DataPreview,
    ResourceType,
    SelectionError,
    UnsupportedConversionError,
)
from bookshelf._consume.selection import Selection
from bookshelf._generated import models
from bookshelf.cache import ContentCache
from tests.test_legacy import BASE_URL, TRACKING_ID, WIDE, _parquet, _platform

DATA_PATH = f"/v1/resources/{TRACKING_ID}/data"
_UNESCAPED_COMMA = re.compile(r"(?<!\\),")


def _year(label: str) -> int | None:
    match = re.match(r"^(\d{4})", label)
    return int(match.group(1)) if match else None


def _served(frame: pd.DataFrame, params: httpx.QueryParams) -> pd.DataFrame | str:
    """Answer ``/data`` the way the platform does for the subset of its grammar the SDK sends."""
    years = [column for column in frame.columns if _year(column) is not None]
    for key, raw in params.multi_items():
        if key in {"limit", "order"} or key.startswith("$"):
            continue
        column, _, op = key.rpartition(".")
        if column not in frame.columns:
            return f"Unknown column in filter: {column}"
        if op == "is":
            frame = frame[frame[column].isna()]
        elif op == "eq":
            frame = frame[frame[column].astype(str) == raw]
        elif op == "in":
            wanted = [part.replace("\\,", ",") for part in _UNESCAPED_COMMA.split(raw)]
            frame = frame[frame[column].astype(str).isin(wanted)]
    low = int(params.get("$year.min", -10_000))
    high = int(params.get("$year.max", 10_000))
    frame = frame.drop(columns=[c for c in years if not low <= (_year(c) or 0) <= high])
    kept = [c for c in years if c in frame.columns]
    # As on the platform, an order replaces the ranking, and top_n then keeps the leading rows.
    if "order" in params:
        keys = [part.rpartition(".") for part in params["order"].split(",")]
        if any(column not in frame.columns for column, _, _ in keys):
            return f"Unknown column in order: {params['order']}"
        frame = frame.sort_values(
            [column for column, _, _ in keys],
            ascending=[direction == "asc" for _, _, direction in keys],
            na_position="first",
        )
    elif "$top_n" in params:
        frame = frame.sort_values(kept[-1], ascending=False)
    else:
        # The platform serves a render sorted on the dimensions, variable first, not the file's order.
        dimensions = [c for c in frame.columns if c not in years]
        keys = sorted(dimensions, key=lambda c: c != "variable")
        frame = frame.sort_values(keys, kind="stable", na_position="last")
    if "$top_n" in params:
        frame = frame.head(int(params["$top_n"]))
    if "limit" in params:
        frame = frame.head(int(params["limit"]))
    return frame.reset_index(drop=True)


def _shelf_transport(
    frame: pd.DataFrame = WIDE, **options: Any
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    inner = _platform([("v2.6", 1)], frame=frame, **options).handler

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == DATA_PATH:
            served = _served(frame, request.url.params)
            if isinstance(served, str):
                return httpx.Response(422, json={"detail": served})
            return httpx.Response(
                200, content=_parquet(served), headers={"content-type": "application/parquet"}
            )
        return inner(request)  # type: ignore[return-value]

    return httpx.MockTransport(handler), seen


def _shelf(tmp_path: Path, **options: Any) -> tuple[Bookshelf, list[httpx.Request]]:
    transport, seen = _shelf_transport(**options)
    bs = Bookshelf(BASE_URL, auth=None, transport=transport, cache=ContentCache(tmp_path / "cache"))
    return bs, seen


def _data_requests(seen: list[httpx.Request]) -> list[httpx.Request]:
    return [request for request in seen if request.url.path == DATA_PATH]


def test_book_entry_as_df_reads_the_whole_file(tmp_path: Path) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    assert entry.as_df().equals(entry.as_resource().as_df())
    assert [request.url.host for request in seen].count("s3.example") == 1
    assert _data_requests(seen) == []


def test_filters_and_the_year_window_apply_to_the_cached_file(tmp_path: Path) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    frame = entry.as_df(filters={"region": "NZL"}, year_min=2001)

    assert list(frame.columns) == ["2001"]
    assert frame.index.get_level_values("region").unique().tolist() == ["NZL"]
    assert len(frame) == 2
    long = entry.as_long_df(filters={"variable": "Emissions|CO2"}, year_max=2000)
    assert long["year"].tolist() == [2000, 2000]
    assert _data_requests(seen) == []


def test_values_listed_for_one_filter_are_alternatives(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)
    resource = bs.resource(TRACKING_ID)

    both = resource.as_df(filters={"region": ["NZL", "AUS"], "variable": "Emissions|CO2"})

    assert sorted(both.index.get_level_values("region")) == ["AUS", "NZL"]


SELECTIONS: list[dict[str, Any]] = [
    {},
    {"filters": {"region": "NZL"}},
    {"filters": {"region": ["NZL", "AUS"], "variable": "Emissions|CO2"}},
    {"year_min": 2001},
    {"filters": {"unit": "Mt CO2/yr"}, "year_max": 2000},
]


def _in_label_order(long: pd.DataFrame) -> pd.DataFrame:
    labels = [column for column in long.columns if column != "value"]
    return long.sort_values(labels, ignore_index=True)


@pytest.mark.parametrize("selection", SELECTIONS)
def test_the_platform_selects_the_same_rows_as_the_cached_file(
    tmp_path: Path, selection: dict[str, Any]
) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    remote = entry.as_df(server_side=True, **selection)

    assert not any(request.url.host == "s3.example" for request in seen)
    pd.testing.assert_frame_equal(remote, entry.as_df(**selection), check_like=True)
    pd.testing.assert_frame_equal(
        _in_label_order(entry.as_long_df(server_side=True, **selection)),
        _in_label_order(entry.as_long_df(**selection)),
    )


def test_without_an_order_a_server_side_read_keeps_the_platform_row_order(tmp_path: Path) -> None:
    """The platform reads a sorted render, so only the rows match the cached file, not their order."""
    bs, _ = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    local = entry.as_df()
    remote = entry.as_df(server_side=True)

    assert remote.index.tolist() != local.index.tolist()
    pd.testing.assert_frame_equal(remote.sort_index(), local.sort_index())
    order = list(local.index.names)
    pd.testing.assert_frame_equal(
        entry.as_df(server_side=True, order=order), entry.as_df(order=order)
    )


def test_a_server_side_read_sends_the_selection(tmp_path: Path) -> None:
    bs, seen = _shelf(tmp_path)

    bs.resource(TRACKING_ID).as_df(
        filters={"region": ["NZL", "AUS"], "scenario": "s"}, year_min=2001, server_side=True
    )

    (request,) = _data_requests(seen)
    assert dict(request.url.params) == {
        "region.in": "NZL,AUS",
        "scenario.eq": "s",
        "$year.min": "2001",
    }
    assert "limit" not in request.url.params, "a complete read never caps the rows"


def test_the_wire_encoding_names_every_operator() -> None:
    """A column called ``limit`` is still a filter, and a comma inside a value stays in it."""
    selection = Selection.build(
        {"limit": 5, "flag": True, "gap": None, "name": ["Korea, Republic of", "World"]},
        year_min=None,
        year_max=2100,
    )

    assert selection.data_params() == {
        "flag.eq": "true",
        "gap.is": "null",
        "limit.eq": "5",
        "name.in": "Korea\\, Republic of,World",
        "$year.max": "2100",
    }


def test_equivalent_selections_are_equal() -> None:
    first = Selection.build({"b": "x", "a": 1}, year_min=None, year_max=None)
    second = Selection.build({"a": 1, "b": "x"}, year_min=None, year_max=None)
    assert first == second


def test_an_unknown_filter_column_raises_the_same_error_on_both_routes(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)
    messages = []
    for server_side in (False, True):
        with pytest.raises(SelectionError, match="regoin") as caught:
            bs.resource(TRACKING_ID).as_df(filters={"regoin": "NZL"}, server_side=server_side)
        assert isinstance(caught.value, KeyError)
        messages.append(str(caught.value))

    local, remote = messages
    assert remote == local
    assert "region, scenario, unit, variable" in remote


@pytest.mark.parametrize(
    ("filters", "error"),
    [
        ({"region": []}, ValueError),
        ({"region": ["NZL", None]}, ValueError),
        ({"region": ["NZL", ""]}, ValueError),
        ({"region": {"NZL": 1}}, TypeError),
        ({"region": [["NZL"]]}, TypeError),
        ({"region": pd.DataFrame({"region": ["NZL"]})}, TypeError),
        ([("region", "NZL")], TypeError),
    ],
)
def test_a_malformed_selection_fails_before_any_request(
    tmp_path: Path, filters: Any, error: type[Exception]
) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]
    before = len(seen)

    with pytest.raises(error):
        entry.as_df(filters=filters)

    assert seen[before:] == []


def test_a_year_window_needs_a_timeseries() -> None:
    with pytest.raises(TypeError, match="timeseries"):
        Selection.build(None, year_min=2000, year_max=None).check(models.ResourceType.tabular)


def test_a_preview_says_when_it_has_left_rows_out(tmp_path: Path) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    cut = entry.preview(limit=2)
    whole = entry.preview(limit=3)

    assert isinstance(cut, DataPreview)
    assert (len(cut.data), cut.completeness) == (2, "partial")
    assert (len(whole.data), whole.completeness) == (3, "complete")
    assert [request.url.params["limit"] for request in _data_requests(seen)] == ["3", "4"]


def test_a_preview_ranks_orders_and_trims_on_the_platform(tmp_path: Path) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    ranked = entry.preview(filters={"variable": "Emissions|CO2"}, top_n=1, drop_constant=True)
    ordered = entry.preview(filters={"variable": "Emissions|CO2"}, order=["-region"])

    first, second = _data_requests(seen)
    assert first.url.params["$top_n"] == "1"
    assert second.url.params["order"] == "region.desc"
    assert ranked.data.index.names == [None], "one series leaves no dimension that varies"
    assert ranked.data["2001"].tolist() == [3.5]
    assert ordered.data.index.get_level_values("region").tolist() == ["NZL", "AUS"]


@pytest.mark.parametrize(
    ("options", "match"), [({"order": "region", "top_n": 1}, "top_n"), ({"order": "-2001"}, "year")]
)
def test_a_preview_refuses_an_order_it_cannot_honour(
    tmp_path: Path, options: dict[str, Any], match: str
) -> None:
    """The platform reads top_n with an order as "the first n", and knows years by stored label."""
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    with pytest.raises(ValueError, match=match):
        entry.preview(**options)

    assert _data_requests(seen) == []


ORDERS: list[Any] = [["region", "variable"], ["-region", "variable"], ["unit", "-2001"]]


@pytest.mark.parametrize("order", ORDERS)
def test_both_routes_order_rows_alike(tmp_path: Path, order: Any) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    local = entry.as_df(order=order)
    remote = entry.as_df(order=order, server_side=True)

    assert remote.index.tolist() == local.index.tolist()
    (request,) = _data_requests(seen)
    assert "order" not in request.url.params, "the platform labels year columns as stored"


def test_missing_values_sort_first_in_either_direction() -> None:
    frame = pd.DataFrame({"x": [2.0, None, 1.0]})
    for order in ("x", "-x"):
        ordered = Selection.build(None, year_min=None, year_max=None, order=order).apply(frame)
        assert ordered["x"].isna().tolist()[0]


@pytest.mark.parametrize("server_side", [False, True])
def test_an_unknown_order_column_raises_a_selection_error(
    tmp_path: Path, server_side: bool
) -> None:
    bs, _ = _shelf(tmp_path)
    with pytest.raises(SelectionError, match="regoin"):
        bs.resource(TRACKING_ID).as_df(order="-regoin", server_side=server_side)


@pytest.mark.parametrize("order", ["", "-", ["region", 3]])
def test_a_malformed_order_fails_before_any_request(tmp_path: Path, order: Any) -> None:
    bs, seen = _shelf(tmp_path)
    resource = bs.resource(TRACKING_ID)
    before = len(seen)
    with pytest.raises(ValueError, match="order"):
        resource.as_df(order=order)
    assert seen[before:] == []


def test_an_entry_and_its_resource_preview_alike(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    from_entry = entry.preview(limit=1, filters={"region": "AUS"})
    from_resource = entry.as_resource().preview(limit=1, filters={"region": "AUS"})

    pd.testing.assert_frame_equal(from_entry.data, from_resource.data)
    assert from_entry.completeness == from_resource.completeness == "complete"


def test_download_leaves_a_copy_the_cache_cannot_evict(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)
    resource = bs.resource(TRACKING_ID)

    copied = resource.download(tmp_path / "out" / "by_country.parquet")
    ContentCache(tmp_path / "cache").clear()

    assert copied == tmp_path / "out" / "by_country.parquet"
    assert pd.read_parquet(copied).equals(WIDE)
    assert list(copied.parent.iterdir()) == [copied]


def test_describe_names_the_reads_the_type_answers(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)

    info = bs.resource(TRACKING_ID).describe()

    assert info.resource_type is ResourceType.TIMESERIES
    assert str(info.tracking_id) == TRACKING_ID
    assert "as_scmrun()" in info.readers
    assert "preview()" in info.readers


def test_drop_constant_needs_a_timeseries(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)
    resource = bs.resource(TRACKING_ID)
    resource._resource_type = models.ResourceType.tabular

    with pytest.raises(UnsupportedConversionError, match="drop_constant"):
        resource.preview(drop_constant=True)


@pytest.mark.parametrize("server_side", [False, True])
def test_int_years_labels_the_year_columns_as_integers(tmp_path: Path, server_side: bool) -> None:
    bs, _ = _shelf(tmp_path)
    resource = bs.resource(TRACKING_ID)

    frame = resource.as_df(year_min=2001, order="-2001", server_side=server_side, int_years=True)

    assert list(frame.columns) == [2001]
    assert frame[2001].tolist() == [3.5, 2.5, 1.5]
    pd.testing.assert_frame_equal(
        frame, resource.as_df(year_min=2001, order="-2001").set_axis([2001], axis=1)
    )


def test_int_years_needs_a_timeseries(tmp_path: Path) -> None:
    bs, seen = _shelf(tmp_path)
    resource = bs.resource(TRACKING_ID)
    resource._resource_type = models.ResourceType.tabular

    with pytest.raises(UnsupportedConversionError):
        resource.as_df(int_years=True)
    assert not any(request.url.host == "s3.example" for request in seen)


def test_an_external_pointer_is_selected_by_the_platform(tmp_path: Path) -> None:
    """The platform reads an external pointer where it lives, which a presigned fetch cannot."""
    bs, seen = _shelf(tmp_path, external=True)

    frame = bs.book("primap-hist", "v2.6")["by_country"].as_df(filters={"region": "NZL"})

    assert len(frame) == 2
    (request,) = _data_requests(seen)
    assert request.url.params["region.eq"] == "NZL"
    assert not any(request.url.scheme == "s3" for request in seen)


async def test_the_async_reads_match_the_sync_ones(tmp_path: Path) -> None:
    transport, seen = _shelf_transport()
    sync_bs = Bookshelf(
        BASE_URL, auth=None, transport=transport, cache=ContentCache(tmp_path / "sync")
    )
    expected = sync_bs.resource(TRACKING_ID).as_df(filters={"region": "AUS"})
    async with AsyncBookshelf(
        BASE_URL, auth=None, async_transport=transport, cache=ContentCache(tmp_path / "async")
    ) as bs:
        book = await bs.book("primap-hist", "v2.6")
        entry = book["by_country"]
        local = await entry.as_df(filters={"region": "AUS"})
        remote = await entry.as_df(filters={"region": "AUS"}, server_side=True)
        years = await entry.as_df(filters={"region": "AUS"}, int_years=True)
        preview = await entry.preview(limit=1)
        info = await entry.describe()

    pd.testing.assert_frame_equal(local, expected)
    pd.testing.assert_frame_equal(remote, expected, check_like=True)
    assert list(years.columns) == [2000, 2001]
    assert preview.completeness == "partial"
    assert info.resource_type is ResourceType.TIMESERIES


def _empty_methane() -> pd.DataFrame:
    frame = WIDE.copy()
    frame.loc[frame["variable"] == "Emissions|CH4", ["2000-01-01", "2001-01-01 00:00:00"]] = float(
        "nan"
    )
    return frame


def test_as_scmrun_keeps_timeseries_with_no_values(tmp_path: Path) -> None:
    pytest.importorskip("scmdata")
    bs, _ = _shelf(tmp_path, frame=_empty_methane())

    run = bs.book("primap-hist", "v2.6")["by_country"].as_scmrun()

    assert len(run) == 3
    assert run.filter(variable="Emissions|CH4").timeseries().isna().all(axis=None)


async def test_the_async_as_scmrun_keeps_timeseries_with_no_values(tmp_path: Path) -> None:
    pytest.importorskip("scmdata")
    transport, _ = _shelf_transport(frame=_empty_methane())
    async with AsyncBookshelf(
        BASE_URL, auth=None, async_transport=transport, cache=ContentCache(tmp_path / "cache")
    ) as bs:
        book = await bs.book("primap-hist", "v2.6")
        run = await book["by_country"].as_scmrun()

    assert len(run) == 3
    assert run.filter(variable="Emissions|CH4").timeseries().isna().all(axis=None)


def test_as_scmrun_rejects_duplicate_metadata(tmp_path: Path) -> None:
    errors = pytest.importorskip("scmdata.errors")
    bs, _ = _shelf(tmp_path, frame=pd.concat([WIDE, WIDE.iloc[:1]], ignore_index=True))

    with pytest.raises(errors.NonUniqueMetadataError):
        bs.book("primap-hist", "v2.6")["by_country"].as_scmrun()


def _select(frame: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    return Selection.build(filters, year_min=None, year_max=None).apply(frame)


@pytest.mark.parametrize("category", [[1, 2, 1], [1.0, 2.0, 1.0], ["1", "2", "1"]])
@pytest.mark.parametrize("wanted", ["1", 1, 1.0])
def test_numbers_match_by_value(category: list[object], wanted: object) -> None:
    frame = pd.DataFrame({"category": category, "value": [1.0, 2.0, 3.0]})
    assert _select(frame, {"category": wanted})["value"].tolist() == [1.0, 3.0]


@pytest.mark.parametrize(
    ("category", "wanted"), [([1, 2], "x"), ([1, 2], 1.5), ([1, 2], True), ([1.0, 2.0], "x")]
)
def test_a_value_the_column_cannot_hold_is_refused_as_on_the_platform(
    category: list[object], wanted: object
) -> None:
    """The platform reads the value as the column's type, and a 422 is a SelectionError."""
    with pytest.raises(SelectionError, match="category"):
        _select(pd.DataFrame({"category": category}), {"category": wanted})


def test_booleans_nullable_numbers_and_missing_values_match_like_the_platform() -> None:
    flags = pd.DataFrame({"flag": [True, False, True]})
    assert len(_select(flags, {"flag": True})) == 2
    assert len(_select(flags, {"flag": "true"})) == 2
    counts = pd.DataFrame({"count": pd.array([1, None, 1], dtype="Int64")})
    assert len(_select(counts, {"count": 1})) == 2
    assert len(_select(counts, {"count": None})) == 1
    labels = pd.DataFrame({"label": ["a", None, "True"]})
    assert len(_select(labels, {"label": None})) == 1
    assert len(_select(labels, {"label": True})) == 0, "the platform spells True as 'true'"


def test_separate_filters_must_all_hold() -> None:
    frame = pd.DataFrame({"a": ["x", "x", "y"], "b": ["p", "q", "p"]})
    assert len(_select(frame, {"a": "x", "b": "p"})) == 1


def test_the_year_window_is_inclusive() -> None:
    wide = pd.DataFrame([[1.0, 2.0, 3.0]], columns=["2000", "2001", "2002"])
    selection = Selection.build(None, year_min=2001, year_max=2002)
    assert list(selection.apply(wide).columns) == ["2001", "2002"]


def test_a_tabular_frame_filters_on_its_columns() -> None:
    frame = pd.DataFrame({"region": ["NZL", "AUS"], "value": [1.0, 2.0]})
    assert _select(frame, {"region": "AUS"})["value"].tolist() == [2.0]


def test_a_tabular_preview_sends_a_digit_named_order_to_the_platform(tmp_path: Path) -> None:
    bs, seen = _shelf(tmp_path)
    resource = bs.resource(TRACKING_ID)
    resource._resource_type = models.ResourceType.tabular

    with pytest.raises(SelectionError, match="order"):
        resource.preview(order="-2020")

    (request,) = _data_requests(seen)
    assert request.url.params["order"] == "2020.desc", "only a timeseries year is refused"


@pytest.mark.parametrize(
    "regions",
    [
        np.array(["NZL", "AUS"]),
        pd.Index(["NZL", "AUS"]),
        pd.Series(["NZL", "AUS"]),
        {"NZL", "AUS"},
        frozenset({"NZL", "AUS"}),
        ("NZL", "AUS"),
    ],
)
def test_numpy_and_pandas_collections_are_filter_values(tmp_path: Path, regions: Any) -> None:
    bs, _ = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    expected = entry.as_df(filters={"region": ["NZL", "AUS"]})

    pd.testing.assert_frame_equal(entry.as_df(filters={"region": regions}), expected)
    pd.testing.assert_frame_equal(
        entry.as_df(filters={"region": regions}, server_side=True), expected, check_like=True
    )


def test_numpy_scalars_are_filter_values_and_years() -> None:
    frame = pd.DataFrame({"category": [1, 2, 1], "flag": [True, False, True]})
    assert len(_select(frame, {"category": np.int64(1)})) == 2
    assert len(_select(frame, {"category": [np.int64(1), np.float64(2.0)]})) == 3
    assert len(_select(frame, {"flag": np.bool_(True)})) == 2
    selection = Selection.build(None, year_min=np.int64(2000), year_max=np.int32(2001))
    assert (selection.year_min, selection.year_max) == (2000, 2001)
    assert type(selection.year_min) is int
    assert Selection.build({"c": np.int64(1)}, year_min=None, year_max=None) == Selection.build(
        {"c": 1}, year_min=None, year_max=None
    )


@pytest.mark.parametrize("year", [True, np.bool_(True), 2000.0, "2000"])
def test_a_year_bound_must_be_an_integer(year: Any) -> None:
    with pytest.raises(TypeError, match="year_min"):
        Selection.build(None, year_min=year, year_max=None)


@pytest.mark.parametrize(
    ("limit", "error"), [(2.5, TypeError), (True, TypeError), ("3", TypeError), (0, ValueError)]
)
def test_a_preview_limit_must_be_a_positive_integer(
    tmp_path: Path, limit: Any, error: type[Exception]
) -> None:
    bs, seen = _shelf(tmp_path)
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    with pytest.raises(error, match="limit"):
        entry.preview(limit=limit)

    assert _data_requests(seen) == []


@pytest.mark.parametrize(("top_n", "error"), [(1.5, TypeError), (True, TypeError), (0, ValueError)])
def test_a_preview_top_n_must_be_a_positive_integer(
    tmp_path: Path, top_n: Any, error: type[Exception]
) -> None:
    bs, seen = _shelf(tmp_path)

    with pytest.raises(error, match="top_n"):
        bs.resource(TRACKING_ID).preview(top_n=top_n)

    assert _data_requests(seen) == []


def test_a_preview_takes_a_numpy_limit(tmp_path: Path) -> None:
    bs, seen = _shelf(tmp_path)

    preview = bs.resource(TRACKING_ID).preview(limit=np.int64(2))

    assert len(preview.data) == 2
    assert [request.url.params["limit"] for request in _data_requests(seen)] == ["3"]


def test_int_years_on_tabular_data_names_int_years(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)
    resource = bs.resource(TRACKING_ID)
    resource._resource_type = models.ResourceType.tabular

    with pytest.raises(UnsupportedConversionError, match="int_years"):
        resource.as_df(int_years=True)


def test_selecting_every_row_and_year_does_not_copy_the_frame() -> None:
    frame = pd.DataFrame({"region": ["World", "World"], "2000": [1.0, 2.0]}).set_index("region")
    selection = Selection.build({"region": "World"}, year_min=1990, year_max=2100)

    assert selection.apply(frame) is frame


def _with_gaps() -> pd.DataFrame:
    frame = WIDE.copy()
    frame.loc[0, "2000-01-01"] = float("nan")
    frame.loc[1, ["2000-01-01", "2001-01-01 00:00:00"]] = float("nan")
    return frame


@pytest.mark.parametrize("server_side", [False, True])
def test_as_long_df_can_drop_missing_values(tmp_path: Path, server_side: bool) -> None:
    bs, _ = _shelf(tmp_path, frame=_with_gaps())
    entry = bs.book("primap-hist", "v2.6")["by_country"]

    full = entry.as_long_df(server_side=server_side)
    dense = entry.as_long_df(server_side=server_side, dropna=True)

    assert len(full) == 6, "missing values stay by default"
    assert len(dense) == 3
    pd.testing.assert_frame_equal(dense, full.dropna(subset=["value"]).reset_index(drop=True))
    with pytest.warns(DeprecationWarning, match="legacy_columns"):
        legacy = entry.as_long_df(server_side=server_side, dropna=True, legacy_columns=True)
    assert legacy["values"].notna().all()
    assert len(legacy) == 3


def test_dropping_missing_values_from_a_frame_with_no_dimensions() -> None:
    from bookshelf._consume.frames import long_timeseries

    wide = pd.DataFrame([[1.0, float("nan")]], columns=["2000", "2001"])

    dense = long_timeseries(wide, dropna=True)

    pd.testing.assert_frame_equal(
        dense, long_timeseries(wide).dropna(subset=["value"]).reset_index(drop=True)
    )


async def test_the_async_as_long_df_can_drop_missing_values(tmp_path: Path) -> None:
    transport, _ = _shelf_transport(frame=_with_gaps())
    async with AsyncBookshelf(
        BASE_URL, auth=None, async_transport=transport, cache=ContentCache(tmp_path / "cache")
    ) as bs:
        book = await bs.book("primap-hist", "v2.6")
        dense = await book["by_country"].as_long_df(dropna=True)

    assert len(dense) == 3


@pytest.mark.parametrize(
    ("version", "edition", "error"),
    [
        (None, None, TypeError),
        ("", None, ValueError),
        (2.6, None, TypeError),
        ("v2.6", -1, ValueError),
        ("v2.6", 0, ValueError),
        ("v2.6", True, TypeError),
        ("v2.6", 1.0, TypeError),
    ],
)
def test_a_malformed_book_coordinate_fails_before_any_request(
    tmp_path: Path, version: Any, edition: Any, error: type[Exception]
) -> None:
    bs, seen = _shelf(tmp_path)

    with pytest.raises(error):
        bs.book("primap-hist", version, edition=edition)

    assert seen == []


async def test_the_async_book_checks_its_coordinate_too(tmp_path: Path) -> None:
    transport, seen = _shelf_transport()
    async with AsyncBookshelf(
        BASE_URL, auth=None, async_transport=transport, cache=ContentCache(tmp_path / "cache")
    ) as bs:
        with pytest.raises(TypeError, match="version"):
            await bs.book("primap-hist", None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="edition"):
            await bs.book("primap-hist", "v2.6", edition=-1)

    assert seen == []


def test_a_numpy_edition_is_an_edition(tmp_path: Path) -> None:
    bs, _ = _shelf(tmp_path)

    book = bs.book("primap-hist", "v2.6", edition=np.int64(1))

    assert book.edition == 1


def test_a_set_of_values_is_sent_in_a_stable_order() -> None:
    selection = Selection.build({"region": {"NZL", "AUS", "CHN"}}, year_min=None, year_max=None)
    assert selection.data_params() == {"region.in": "AUS,CHN,NZL"}


def test_dropping_missing_values_keeps_a_nullable_dtype() -> None:
    from bookshelf._consume.frames import long_timeseries

    wide = pd.DataFrame(
        {"region": ["NZL", "AUS"], "2000": pd.array([1, None], dtype="Int64")}
    ).set_index("region")

    dense = long_timeseries(wide, dropna=True)

    assert str(dense["value"].dtype) == "Int64"
    pd.testing.assert_frame_equal(
        dense, long_timeseries(wide).dropna(subset=["value"]).reset_index(drop=True)
    )


def test_a_failed_column_probe_still_reports_the_unknown_column(tmp_path: Path) -> None:
    transport, seen = _shelf_transport()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == DATA_PATH and request.url.params.get("limit") == "1":
            return httpx.Response(403, json={"detail": "forbidden"})
        return transport.handler(request)  # type: ignore[no-any-return]

    bs = Bookshelf(
        BASE_URL,
        auth=None,
        transport=httpx.MockTransport(handler),
        cache=ContentCache(tmp_path / "cache"),
    )

    with pytest.raises(SelectionError, match="Unknown column in filter: regoin"):
        bs.resource(TRACKING_ID).as_df(filters={"regoin": "NZL"}, server_side=True)


def test_dictionary_encoded_labels_take_numpy_filters_and_drop_missing_values(
    tmp_path: Path,
) -> None:
    """A cached wide read keeps its labels as parquet dictionaries, and the platform's are plain."""
    bs, _ = _shelf(tmp_path, frame=_with_gaps())
    entry = bs.book("primap-hist", "v2.6")["by_country"]
    regions = np.array(["NZL", "AUS"])

    local = entry.as_long_df(filters={"region": regions}, dropna=True)
    remote = entry.as_long_df(filters={"region": regions}, dropna=True, server_side=True)

    assert len(local) == 3
    pd.testing.assert_frame_equal(_in_label_order(local), _in_label_order(remote))
    pd.testing.assert_frame_equal(
        local, entry.as_long_df(filters={"region": regions}).dropna().reset_index(drop=True)
    )
    messages = []
    for server_side in (False, True):
        with pytest.raises(SelectionError) as caught:
            entry.as_df(filters={"regoin": regions}, server_side=server_side)
        messages.append(str(caught.value))
    assert messages[0] == messages[1]


class _ClearedOnce(ContentCache):
    """A cache another process clears once, just after handing out a verified path."""

    cleared = False

    def _clear_once(self, path: Path) -> Path:
        if not self.cleared:
            self.cleared = True
            self.clear()
        return path

    def fetch(self, content_hash: str, download: Any) -> Path:
        return self._clear_once(super().fetch(content_hash, download))

    async def fetch_async(self, content_hash: str, download: Any) -> Path:
        return self._clear_once(await super().fetch_async(content_hash, download))


@pytest.mark.parametrize("read", ["as_df", "fetch"])
def test_a_cache_cleared_under_a_read_downloads_again(tmp_path: Path, read: str) -> None:
    transport, seen = _shelf_transport()
    cache = _ClearedOnce(tmp_path / "cache")
    bs = Bookshelf(BASE_URL, auth=None, transport=transport, cache=cache)
    resource = bs.resource(TRACKING_ID)

    result = getattr(resource, read)()

    assert cache.cleared
    assert [request.url.host for request in seen].count("s3.example") == 2
    expected = resource.as_df() if read == "as_df" else _parquet(WIDE)
    assert result.equals(expected) if read == "as_df" else result == expected


@pytest.mark.parametrize("read", ["as_df", "fetch"])
async def test_a_cache_cleared_under_an_async_read_downloads_again(
    tmp_path: Path, read: str
) -> None:
    transport, seen = _shelf_transport()
    cache = _ClearedOnce(tmp_path / "cache")
    async with AsyncBookshelf(BASE_URL, auth=None, async_transport=transport, cache=cache) as bs:
        resource = await bs.resource(TRACKING_ID)
        result = await getattr(resource, read)()
        expected = await resource.as_df() if read == "as_df" else _parquet(WIDE)

    assert cache.cleared
    assert [request.url.host for request in seen].count("s3.example") == 2
    assert result.equals(expected) if read == "as_df" else result == expected


@pytest.mark.parametrize("missing", [float("nan"), np.nan, np.float32("nan"), pd.NA, pd.NaT])
def test_a_missing_filter_value_selects_like_none(missing: object) -> None:
    built = Selection.build({"region": missing}, year_min=None, year_max=None)

    assert built == Selection.build({"region": None}, year_min=None, year_max=None)
    assert built.data_params() == {"region.is": "null"}


@pytest.mark.parametrize("server_side", [False, True])
def test_a_nan_filter_picks_the_missing_rows_on_both_routes(
    tmp_path: Path, server_side: bool
) -> None:
    gappy = WIDE.assign(region=["NZL", None, "AUS"])
    bs, _ = _shelf(tmp_path, frame=gappy)
    resource = bs.resource(TRACKING_ID)

    picked = resource.as_df(filters={"region": np.nan}, server_side=server_side)

    assert picked.index.get_level_values("variable").tolist() == ["Emissions|CH4"]


@pytest.mark.parametrize("server_side", [False, True])
def test_a_nan_among_other_filter_values_is_refused_like_none(
    tmp_path: Path, server_side: bool
) -> None:
    """pandas reads the unique labels of a gappy column back with a NaN among them."""
    bs, seen = _shelf(tmp_path)
    resource = bs.resource(TRACKING_ID)
    before = len(seen)

    with pytest.raises(ValueError, match="'region' can match a missing value"):
        resource.as_df(filters={"region": ["NZL", np.nan]}, server_side=server_side)
    assert seen[before:] == []
