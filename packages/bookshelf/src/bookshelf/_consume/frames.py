"""Pure dataframe conversions for consumed resources."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING

from bookshelf._core.frames import require_package

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa


_DATED_YEAR = re.compile(r"^(\d{4})-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?$")


def year_label(column: object) -> str:
    """Reduce a dated column such as ``2000-01-01`` or ``2000-01-01 00:00:00`` to its year."""
    match = _DATED_YEAR.match(str(column))
    return match.group(1) if match else str(column)


def is_year_column(column: object) -> bool:
    """Whether a wide frame's column is a year, which a shaped frame labels as a digit string."""
    return str(column).isdigit()


def wide_timeseries(frame: pd.DataFrame, coded: Collection[str] = ()) -> pd.DataFrame:
    """Normalise long or wide timeseries data to indexed wide pandas with string year labels.

    A stored wide file stamps each year column with a full date,
    so those are reduced to the bare year first.
    ``coded`` names text dimensions read as dictionaries, whose codes build the index directly.
    The result then shares its year columns with ``frame``.
    """
    if {"year", "value"} <= set(frame.columns):
        dimensions = [column for column in frame.columns if column not in {"year", "value"}]
        if not dimensions:
            wide = frame.set_index("year")["value"].to_frame().T
        else:
            wide = frame.pivot(index=dimensions, columns="year", values="value")
        wide.columns = [str(column) for column in wide.columns]
        return wide
    frame = frame.copy(deep=False)
    frame.columns = [year_label(column) for column in frame.columns]
    dimensions = [column for column in frame.columns if not is_year_column(column)]
    if not dimensions:
        return frame
    if not coded:
        return frame.set_index(dimensions)
    index = _dimension_index(frame, dimensions, coded)
    # Deleting from the shallow copy, unlike drop(), spares pandas 2 a copy of every year column.
    for column in dimensions:
        del frame[column]
    frame.index = index
    return frame


def _dimension_index(
    frame: pd.DataFrame, dimensions: list[str], coded: Collection[str]
) -> pd.MultiIndex:
    """Build the index ``set_index`` would, reusing categorical codes instead of hashing every row."""
    import pandas as pd

    levels = []
    codes = []
    for column in dimensions:
        values = frame[column].array
        if column not in coded or not isinstance(values, pd.Categorical):
            values = pd.Categorical(frame[column])
        elif len(categories := values.remove_unused_categories().categories):
            values = values.set_categories(categories.sort_values())
        else:
            # An all-missing dictionary loses the text type the dense column would keep.
            values = values.set_categories(pd.Index([], dtype=pd.Index([""]).dtype))
        levels.append(values.categories)
        codes.append(values.codes)
    return pd.MultiIndex(levels=levels, codes=codes, names=dimensions, verify_integrity=False)


def int_year_columns(wide: pd.DataFrame) -> pd.DataFrame:
    """Relabel a shaped wide frame's year columns as integers."""
    return wide.rename(columns=lambda column: int(column) if is_year_column(column) else column)


def long_timeseries(frame: pd.DataFrame, *, dropna: bool = False) -> pd.DataFrame:
    """Normalize long or wide timeseries data to tidy pandas.

    ``dropna`` leaves out the rows with no value.
    """
    if {"year", "value"} <= set(frame.columns):
        long = frame.dropna(subset=["value"]) if dropna else frame
        return long.reset_index(drop=True)
    wide = wide_timeseries(frame)
    # A wide frame of nothing but year columns carries no dimensions,
    # so its positional index is not something to melt on.
    dimensions = [name for name in wide.index.names if name is not None]
    import numpy as np

    # Extension dtypes such as Int64 would lose their type through to_numpy, so they melt.
    if dropna and all(isinstance(dtype, np.dtype) for dtype in wide.dtypes):
        return _dense_long(wide, dimensions)
    long = wide.reset_index(drop=not dimensions).melt(
        id_vars=dimensions,
        var_name="year",
        value_name="value",
    )
    long["year"] = long["year"].astype(int)
    return long.dropna(subset=["value"]).reset_index(drop=True) if dropna else long


def _dense_long(wide: pd.DataFrame, dimensions: list[str]) -> pd.DataFrame:
    """Melt only the cells holding a value, in the order melt would leave them."""
    import numpy as np
    import pandas as pd

    values = wide.to_numpy().T
    present = pd.notna(values)
    year_at, row_at = np.nonzero(present)
    long: pd.DataFrame
    if dimensions:
        long = wide.index.take(row_at).to_frame(index=False)
    else:
        long = pd.DataFrame(index=pd.RangeIndex(len(row_at)))
    long["year"] = np.array([int(column) for column in wide.columns], dtype=np.int64)[year_at]
    long["value"] = values[present]
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


def drop_constant_dimensions(wide: pd.DataFrame) -> pd.DataFrame:
    """Drop the index levels that hold one value across the rows of a wide timeseries frame."""
    constant = [
        name
        for name in wide.index.names
        if name is not None and wide.index.get_level_values(name).nunique(dropna=False) <= 1
    ]
    return wide.reset_index(level=constant, drop=True) if constant else wide


def polars_converter() -> Callable[[pd.DataFrame], pl.DataFrame]:
    """Import Polars and return a converter that keeps the index columns.

    Callers resolve the converter before fetching any data,
    so an install without polars fails without making a request.
    """
    polars = require_package("polars", "as_polars()")

    def convert(frame: pd.DataFrame) -> pl.DataFrame:
        return polars.from_pandas(frame, include_index=True)  # type: ignore[no-any-return]

    return convert


def arrow_converter() -> Callable[[pd.DataFrame], pa.Table]:
    """Return a converter to a PyArrow table that keeps the index columns."""
    import pyarrow as pa

    def convert(frame: pd.DataFrame) -> pa.Table:
        return pa.Table.from_pandas(frame, preserve_index=True)

    return convert


__all__ = [
    "arrow_converter",
    "drop_constant_dimensions",
    "int_year_columns",
    "is_year_column",
    "legacy_long_timeseries",
    "long_timeseries",
    "polars_converter",
    "wide_timeseries",
    "year_label",
]
