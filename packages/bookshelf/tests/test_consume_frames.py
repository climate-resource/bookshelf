"""Tests for the consumed-resource frame conversions (``bookshelf._consume.frames``)."""

import sys

import pandas as pd
import pytest

from bookshelf import DataFrameSupportError
from bookshelf._consume.frames import (
    drop_constant_dimensions,
    long_timeseries,
    polars_converter,
    wide_timeseries,
)


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


@pytest.mark.parametrize(
    "stored",
    [
        pd.DataFrame({"region": ["NZL"], "2000-01-01": [1.5], "2001-01-01 00:00:00": [2.5]}),
        pd.DataFrame({"region": ["NZL", "NZL"], "year": [2000, 2001], "value": [1.5, 2.5]}),
    ],
    ids=["wide", "long"],
)
def test_wide_timeseries_labels_years_as_strings_whatever_the_stored_shape(
    stored: pd.DataFrame,
) -> None:
    wide = wide_timeseries(stored)
    assert list(wide.columns) == ["2000", "2001"]
    assert wide.loc["NZL", "2000"] == 1.5


def test_a_long_frame_without_dimensions_still_gets_string_years() -> None:
    wide = wide_timeseries(pd.DataFrame({"year": [2000, 2001], "value": [1.5, 2.5]}))
    assert list(wide.columns) == ["2000", "2001"]


def test_drop_constant_dimensions_keeps_the_levels_that_vary() -> None:
    wide = pd.DataFrame(
        {"model": ["m", "m"], "region": ["NZL", "AUS"], "2000": [1.0, 2.0]}
    ).set_index(["model", "region"])
    assert drop_constant_dimensions(wide).index.names == ["region"]
    assert drop_constant_dimensions(wide.iloc[:1]).index.names == [None]


def test_wide_timeseries_leaves_a_year_only_frame_alone() -> None:
    wide = pd.DataFrame({"2000": [1.5]})
    assert list(wide_timeseries(wide).columns) == ["2000"]


def test_a_missing_polars_fails_when_the_converter_is_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The converter is resolved before any request, so a missing polars costs no download."""
    monkeypatch.setitem(sys.modules, "polars", None)

    with pytest.raises(DataFrameSupportError) as raised:
        polars_converter()

    assert "as_polars()" in str(raised.value)


def test_wide_timeseries_keeps_categorical_dimensions_it_was_handed() -> None:
    """A /data payload can carry categoricals, which only a dictionary read may flatten."""
    stored = pd.DataFrame(
        {
            "region": pd.Categorical(
                ["NZL", "AUS"], categories=["NZL", "AUS", "USA"], ordered=True
            ),
            "variable": ["a", "b"],
            "2000-01-01": [1.0, 2.0],
        }
    )

    pd.testing.assert_frame_equal(
        wide_timeseries(stored),
        stored.rename(columns={"2000-01-01": "2000"}).set_index(["region", "variable"]),
    )
