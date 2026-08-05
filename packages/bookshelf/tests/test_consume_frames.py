"""Tests for the consumed-resource frame conversions (``bookshelf._consume.frames``)."""

import sys

import pandas as pd
import pytest

from bookshelf._consume.frames import (
    arrow_converter,
    long_timeseries,
    polars_converter,
    timeseries_frame,
    wide_timeseries,
)
from bookshelf._core.errors import BookshelfError
from bookshelf._core.frames import DataFrameSupportError
from bookshelf._generated import models


def test_long_timeseries_round_trips_a_dimensioned_wide_frame() -> None:
    wide = pd.DataFrame({"region": ["NZL"], "2000": [1.5], "2001": [2.5]})
    long = long_timeseries(wide)
    assert list(long.columns) == ["region", "year", "value"]
    assert long["year"].tolist() == [2000, 2001]


def test_long_timeseries_handles_a_wide_frame_without_dimensions() -> None:
    """A frame of nothing but year columns has no index to melt on."""
    wide = pd.DataFrame({"2000": [1.5], "2001": [2.5]})
    long = long_timeseries(wide)
    assert list(long.columns) == ["year", "value"]
    assert long["year"].tolist() == [2000, 2001]
    assert long["value"].tolist() == [1.5, 2.5]


def test_long_timeseries_handles_a_response_without_an_index() -> None:
    response = models.TimeseriesResponse(
        index=[],
        years=[2000, 2001],
        data=[[1.5, 2.5]],
        metadata={},
        total_rows=1,
    )
    long = long_timeseries(timeseries_frame(response))
    assert list(long.columns) == ["year", "value"]
    assert long["value"].tolist() == [1.5, 2.5]


def test_wide_timeseries_leaves_a_year_only_frame_alone() -> None:
    wide = pd.DataFrame({"2000": [1.5]})
    assert list(wide_timeseries(wide).columns) == ["2000"]


@pytest.mark.parametrize(
    ("module", "converter", "method"),
    [
        ("polars", polars_converter, "as_polars()"),
        ("pyarrow", arrow_converter, "as_arrow()"),
    ],
)
def test_a_missing_extra_is_reported_as_a_bookshelf_error(
    monkeypatch: pytest.MonkeyPatch,
    module: str,
    converter: object,
    method: str,
) -> None:
    """A caller catching BookshelfError should not have to catch ImportError as well."""
    monkeypatch.setitem(sys.modules, module, None)

    with pytest.raises(DataFrameSupportError) as raised:
        converter()  # type: ignore[operator]

    assert isinstance(raised.value, BookshelfError)
    assert method in str(raised.value)
    assert "pip install 'bookshelf[dataframes]'" in str(raised.value)
