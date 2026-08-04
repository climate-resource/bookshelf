"""Tests for the consumed-resource frame conversions (``bookshelf._consume.frames``)."""

import pandas as pd

from bookshelf._consume.frames import long_timeseries, timeseries_frame, wide_timeseries
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
