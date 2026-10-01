"""A cached parquet read plans part of the selection in pyarrow, and answers exactly as pandas would."""

from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest

from bookshelf._consume.reading import settle_cached
from bookshelf._consume.resources import _read_cached
from bookshelf._consume.selection import Selection
from bookshelf._core.errors import SelectionError
from bookshelf._core.frames import read_frame
from bookshelf._generated import models
from tests.test_legacy import WIDE

TIMESERIES = models.ResourceType.timeseries
TABULAR = models.ResourceType.tabular

LONG = pd.DataFrame(
    {
        "region": ["NZL", "NZL", "AUS", "AUS"],
        "variable": ["Emissions|CO2"] * 4,
        "year": [2000, 2001, 2000, 2001],
        "value": [1.0, 1.5, 3.0, 3.5],
    }
)

TABLE = pd.DataFrame(
    {
        "code": ["NA", "NZ", None, "AU"],
        "count": [1, 2, 3, 4],
        "share": [0.5, float("nan"), 1.5, 2.0],
        "flag": [True, False, True, False],
    }
)


def _store(tmp_path: Path, frame: pd.DataFrame, **options: Any) -> Path:
    path = tmp_path / "resource"
    if options:
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path, **options)
    else:
        frame.to_parquet(path)
    return path


def _unplanned(resource_type: models.ResourceType, path: Path, selection: Selection) -> Any:
    return settle_cached(resource_type, read_frame(path), selection)


CASES: list[tuple[models.ResourceType, pd.DataFrame, dict[str, Any]]] = [
    (TIMESERIES, WIDE, {}),
    (TIMESERIES, WIDE, {"filters": {"region": "NZL"}}),
    (TIMESERIES, WIDE, {"filters": {"region": ["NZL", "AUS"], "variable": "Emissions|CO2"}}),
    (TIMESERIES, WIDE, {"year_min": 2001}),
    (TIMESERIES, WIDE, {"filters": {"unit": "Mt CO2/yr"}, "year_max": 2000}),
    (TIMESERIES, WIDE, {"year_min": 1990, "year_max": 1995}),
    (TIMESERIES, WIDE, {"filters": {"region": "XXX"}}),
    (TIMESERIES, LONG, {"filters": {"region": "AUS"}, "year_min": 2001}),
    (TABULAR, TABLE, {"filters": {"code": "NA"}}),
    (TABULAR, TABLE, {"filters": {"code": None}}),
    (TABULAR, TABLE, {"filters": {"code": ""}}),
    (TABULAR, TABLE, {"filters": {"share": None}}),
    (TABULAR, TABLE, {"filters": {"count": [2, 4.0]}}),
    (TABULAR, TABLE, {"filters": {"flag": "true", "code": ["NA", "AU"]}}),
]


@pytest.mark.parametrize("writer", ["pandas", "dictionary", "row groups"])
@pytest.mark.parametrize(("resource_type", "frame", "selection"), CASES)
def test_a_planned_read_matches_reading_the_whole_file(
    tmp_path: Path,
    writer: str,
    resource_type: models.ResourceType,
    frame: pd.DataFrame,
    selection: dict[str, Any],
) -> None:
    options: dict[str, Any] = {
        "pandas": {},
        "dictionary": {"use_dictionary": True},
        "row groups": {"row_group_size": 1, "write_statistics": True},
    }[writer]
    path = _store(tmp_path, frame, **options)
    built = Selection.build(
        selection.get("filters"),
        year_min=selection.get("year_min"),
        year_max=selection.get("year_max"),
    )

    planned = _read_cached(resource_type, path, built)
    # pandas 2 infers an empty index's type from how the empty frame was made.
    pd.testing.assert_frame_equal(
        planned, _unplanned(resource_type, path, built), check_index_type=not planned.empty
    )


def test_an_unknown_filter_column_still_raises(tmp_path: Path) -> None:
    path = _store(tmp_path, WIDE)
    selection = Selection.build({"regoin": "NZL"}, year_min=2001, year_max=None)

    with pytest.raises(SelectionError, match="regoin"):
        _read_cached(TIMESERIES, path, selection)


def test_the_year_window_skips_columns_outside_it() -> None:
    selection = Selection.build({"region": "NZL"}, year_min=2001, year_max=None)

    scan = selection.parquet_scan(TIMESERIES, pa.Schema.from_pandas(WIDE, preserve_index=False))

    assert scan.columns == [
        "model",
        "region",
        "scenario",
        "unit",
        "variable",
        "2001-01-01 00:00:00",
    ]
    assert pa.Table.from_pandas(WIDE).filter(scan.rows)["region"].to_pylist() == ["NZL", "NZL"]


def test_only_filters_pandas_would_read_the_same_way_are_planned() -> None:
    schema = pa.Schema.from_pandas(TABLE, preserve_index=False)

    for filters in ({"count": 2}, {"share": 0.5}, {"flag": True}):
        assert (
            Selection.build(filters, year_min=None, year_max=None)
            .parquet_scan(TABULAR, schema)
            .rows
            is None
        )
    long = pa.Schema.from_pandas(LONG, preserve_index=False)
    scan = Selection.build({"year": 2000}, year_min=2000, year_max=None).parquet_scan(
        TIMESERIES, long
    )
    assert scan == (None, None), "a long file's year rows are whole series once pivoted"


def test_the_planned_filter_skips_row_groups_with_statistics(tmp_path: Path) -> None:
    frame = pd.DataFrame({"region": ["AUS"] * 4 + ["NZL"] * 4, "2000": range(8)})
    path = _store(tmp_path, frame, row_group_size=2, write_statistics=True)
    selection = Selection.build({"region": "NZL"}, year_min=None, year_max=None)
    scan = selection.parquet_scan(TIMESERIES, pq.read_schema(path))

    (fragment,) = ds.dataset(path).get_fragments()

    assert len(fragment.split_by_row_group(scan.rows)) == 2
