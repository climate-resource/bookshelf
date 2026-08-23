"""Pure dataframe conversions for consumed resources."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from bookshelf._core.frames import require_extra
from bookshelf._generated import models

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa


_DATED_YEAR = re.compile(r"^(\d{4})-\d{2}-\d{2}$")


def _year_column(column: object) -> str:
    """Reduce a dated column name such as ``2000-01-01`` to its year, leaving others alone."""
    match = _DATED_YEAR.match(str(column))
    return match.group(1) if match else str(column)


def wide_timeseries(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize long or wide timeseries data to indexed wide pandas.

    A stored wide file stamps each year column with a full date,
    so those are reduced to the bare year first.
    """
    if {"year", "value"} <= set(frame.columns):
        dimensions = [column for column in frame.columns if column not in {"year", "value"}]
        if not dimensions:
            return frame.set_index("year")["value"].to_frame().T
        return frame.pivot(index=dimensions, columns="year", values="value")
    frame = frame.copy(deep=False)
    frame.columns = [_year_column(column) for column in frame.columns]
    dimensions = [column for column in frame.columns if not str(column).isdigit()]
    if dimensions:
        return frame.set_index(dimensions)
    return frame


def long_timeseries(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize long or wide timeseries data to tidy pandas."""
    if {"year", "value"} <= set(frame.columns):
        return frame.reset_index(drop=True)
    wide = wide_timeseries(frame)
    # A wide frame of nothing but year columns carries no dimensions,
    # so its positional index is not something to melt on.
    dimensions = [name for name in wide.index.names if name is not None]
    long = wide.reset_index(drop=not dimensions).melt(
        id_vars=dimensions,
        var_name="year",
        value_name="value",
    )
    long["year"] = long["year"].astype(int)
    return long


def legacy_long_timeseries(frame: pd.DataFrame) -> pd.DataFrame:
    """Shape tidy timeseries data the way the 0.4 long format files were written.

    The value column is ``values``, the year is a ``YYYY-01-01 00:00:00`` string,
    and the rows are sorted by every dimension and then the year.
    """
    long = long_timeseries(frame)
    dimensions = [column for column in long.columns if column not in {"year", "value"}]
    long = long.sort_values([*dimensions, "year"], kind="stable", ignore_index=True)
    long["year"] = long["year"].astype(str).str.zfill(4) + "-01-01 00:00:00"
    return long.rename(columns={"value": "values"})


def timeseries_frame(response: models.TimeseriesResponse) -> pd.DataFrame:
    """Build wide indexed pandas directly from a server timeseries response."""
    import pandas as pd

    index_frame = pd.DataFrame(response.index)
    index = pd.MultiIndex.from_frame(index_frame) if not index_frame.empty else None
    return pd.DataFrame(response.data, index=index, columns=response.years)


def polars_converter() -> Callable[[pd.DataFrame], pl.DataFrame]:
    """Import Polars and return a converter that keeps the index columns.

    Callers resolve the converter before fetching any data,
    so an install without the optional extra fails without making a request.
    """
    polars = require_extra("polars", "as_polars()")

    def convert(frame: pd.DataFrame) -> pl.DataFrame:
        return polars.from_pandas(frame, include_index=True)  # type: ignore[no-any-return]

    return convert


def arrow_converter() -> Callable[[pd.DataFrame], pa.Table]:
    """Import PyArrow and return a converter that keeps the index columns.

    Callers resolve the converter before fetching any data,
    so an install without the optional extra fails without making a request.
    """
    pyarrow = require_extra("pyarrow", "as_arrow()")

    def convert(frame: pd.DataFrame) -> pa.Table:
        return pyarrow.Table.from_pandas(frame, preserve_index=True)

    return convert


__all__ = [
    "arrow_converter",
    "legacy_long_timeseries",
    "long_timeseries",
    "polars_converter",
    "timeseries_frame",
    "wide_timeseries",
]
