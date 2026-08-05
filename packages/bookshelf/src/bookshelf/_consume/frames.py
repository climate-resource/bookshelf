"""Pure dataframe conversions for consumed resources."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from bookshelf._core.frames import DataFrameSupportError
from bookshelf._generated import models

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa


def wide_timeseries(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize long or wide timeseries data to indexed wide pandas."""
    if {"year", "value"} <= set(frame.columns):
        dimensions = [column for column in frame.columns if column not in {"year", "value"}]
        if not dimensions:
            return frame.set_index("year")["value"].to_frame().T
        return frame.pivot(index=dimensions, columns="year", values="value")
    year_columns = [column for column in frame.columns if str(column).isdigit()]
    dimensions = [column for column in frame.columns if column not in year_columns]
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


def timeseries_frame(response: models.TimeseriesResponse) -> pd.DataFrame:
    """Build wide indexed pandas directly from a server timeseries response."""
    import pandas as pd

    index_frame = pd.DataFrame(response.index)
    index = pd.MultiIndex.from_frame(index_frame) if not index_frame.empty else None
    return pd.DataFrame(response.data, index=index, columns=response.years)


def _require(module: str, caller: str) -> Any:
    """Import an optional dependency, reporting a missing extra as a typed error."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise DataFrameSupportError(
            f"{caller} requires the 'dataframes' extra: pip install 'bookshelf[dataframes]'"
        ) from exc


def polars_converter() -> Callable[[pd.DataFrame], pl.DataFrame]:
    """Import Polars and return a converter that keeps the index columns.

    Callers resolve the converter before fetching any data,
    so an install without the optional extra fails without making a request.
    """
    polars = _require("polars", "as_polars()")

    def convert(frame: pd.DataFrame) -> pl.DataFrame:
        return polars.from_pandas(frame, include_index=True)  # type: ignore[no-any-return]

    return convert


def arrow_converter() -> Callable[[pd.DataFrame], pa.Table]:
    """Import PyArrow and return a converter that keeps the index columns.

    Callers resolve the converter before fetching any data,
    so an install without the optional extra fails without making a request.
    """
    pyarrow = _require("pyarrow", "as_arrow()")

    def convert(frame: pd.DataFrame) -> pa.Table:
        return pyarrow.Table.from_pandas(frame, preserve_index=True)

    return convert


__all__ = [
    "arrow_converter",
    "long_timeseries",
    "polars_converter",
    "timeseries_frame",
    "wide_timeseries",
]
