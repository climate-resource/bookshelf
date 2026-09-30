"""The one selection language every read takes, and its two executions.

A selection is the same whether the rows are picked from the cached file or by the platform,
so this module owns its validation, its local matching and its wire encoding.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models

if TYPE_CHECKING:
    import pandas as pd

type FilterValue = str | int | float | bool | None
type Filters = Mapping[str, FilterValue | Sequence[FilterValue]]

_TRUE_WORDS = frozenset({"true", "1", "yes"})


class SelectionError(BookshelfError, ValueError):
    """A selection names a column the resource has not got, or cannot be expressed."""


def _scalar(column: str, value: object) -> FilterValue:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise SelectionError(f"filter {column!r} has a {type(value).__name__} value, not a scalar")


def _values(column: str, wanted: object) -> tuple[FilterValue, ...]:
    if isinstance(wanted, str) or not isinstance(wanted, Sequence):
        return (_scalar(column, wanted),)
    values = tuple(_scalar(column, value) for value in wanted)
    if not values:
        raise SelectionError(f"filter {column!r} lists no values, so it would select nothing")
    if None in values and len(values) > 1:
        raise SelectionError(f"filter {column!r} cannot combine None with other values")
    return values


def wire_text(value: FilterValue) -> str:
    """Spell a filter value the way the platform reads it back."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _escaped(value: FilterValue) -> str:
    return wire_text(value).replace("\\", "\\\\").replace(",", "\\,")


@dataclass(frozen=True, slots=True)
class Selection:
    """Validated filters and an inclusive year window.

    Values within one filter are alternatives, and separate filters must all hold.
    """

    filters: tuple[tuple[str, tuple[FilterValue, ...]], ...] = ()
    year_min: int | None = None
    year_max: int | None = None

    @classmethod
    def build(
        cls,
        filters: Filters | None,
        *,
        year_min: int | None,
        year_max: int | None,
    ) -> Selection:
        """Validate a caller's selection before anything is fetched."""
        if filters is not None and not isinstance(filters, Mapping):
            raise TypeError("filters must be a mapping of column name to value or values")
        for name, bound in (("year_min", year_min), ("year_max", year_max)):
            if bound is not None and (isinstance(bound, bool) or not isinstance(bound, int)):
                raise TypeError(f"{name} must be an integer year")
        normalised = sorted(
            (str(column), _values(str(column), wanted))
            for column, wanted in (filters or {}).items()
        )
        return cls(tuple(normalised), year_min, year_max)

    @property
    def has_years(self) -> bool:
        return self.year_min is not None or self.year_max is not None

    def check(self, resource_type: models.ResourceType) -> None:
        """Refuse a year window on data that has no year columns."""
        if self.has_years and resource_type is not models.ResourceType.timeseries:
            raise SelectionError("year_min and year_max need a timeseries resource")

    def data_params(self) -> dict[str, str]:
        """Encode the selection for the ``/data`` route.

        Every filter names its operator, so a column called ``limit`` is not read as the modifier.
        """
        params: dict[str, str] = {}
        for column, values in self.filters:
            if values == (None,):
                params[f"{column}.is"] = "null"
            elif len(values) == 1:
                params[f"{column}.eq"] = wire_text(values[0])
            else:
                params[f"{column}.in"] = ",".join(_escaped(value) for value in values)
        if self.year_min is not None:
            params["$year.min"] = str(self.year_min)
        if self.year_max is not None:
            params["$year.max"] = str(self.year_max)
        return params

    def book_params(self) -> dict[str, str | list[str]]:
        """Encode the filters for a book route, which repeats a key for alternatives."""
        params: dict[str, str | list[str]] = {}
        for column, values in self.filters:
            if None in values:
                raise SelectionError(f"book routes cannot filter {column!r} on a missing value")
            texts = [wire_text(value) for value in values]
            params[column] = texts[0] if len(texts) == 1 else texts
        if self.year_min is not None:
            params["year.min"] = str(self.year_min)
        if self.year_max is not None:
            params["year.max"] = str(self.year_max)
        return params

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Pick the selected rows and year columns out of a shaped frame."""
        return _filter_years(_filter_rows(frame, self.filters), self.year_min, self.year_max)


def _matches(values: pd.Series[Any] | pd.Index[Any], wanted: FilterValue) -> Any:
    """Compare as the platform does, reading the wanted value as the column's type."""
    import numpy as np
    import pandas as pd
    from pandas.api.types import is_bool_dtype, is_numeric_dtype

    series = pd.Series(values)
    if wanted is None:
        return series.isna().to_numpy(dtype=bool)
    if is_bool_dtype(series.dtype):
        flag = wanted if isinstance(wanted, bool) else wire_text(wanted).lower() in _TRUE_WORDS
        return (series == flag).fillna(False).to_numpy(dtype=bool)
    if is_numeric_dtype(series.dtype):
        try:
            number = float(wanted)
        except ValueError:
            return np.zeros(len(series), dtype=bool)
        return (series == number).fillna(False).to_numpy(dtype=bool)
    return (series.notna() & (series.astype(str) == wire_text(wanted))).to_numpy(dtype=bool)


def _filter_rows(
    frame: pd.DataFrame, filters: tuple[tuple[str, tuple[FilterValue, ...]], ...]
) -> pd.DataFrame:
    import numpy as np

    names = [name for name in frame.index.names if name is not None]
    mask = np.ones(len(frame), dtype=bool)
    for column, values in filters:
        source: pd.Series[Any] | pd.Index[Any]
        if column in frame.columns:
            source = frame[column]
        elif column in names:
            source = frame.index.get_level_values(column)
        else:
            columns = [column for column in frame.columns if not str(column).isdigit()]
            known = ", ".join(map(str, [*names, *columns]))
            raise SelectionError(f"cannot filter on {column!r}, the columns are: {known}")
        either = np.zeros(len(frame), dtype=bool)
        for wanted in values:
            either |= _matches(source, wanted)
        mask &= either
    return frame[mask]


def _filter_years(wide: pd.DataFrame, year_min: int | None, year_max: int | None) -> pd.DataFrame:
    if year_min is None and year_max is None:
        return wide
    low = year_min if year_min is not None else -math.inf
    high = year_max if year_max is not None else math.inf
    return wide[
        [
            column
            for column in wide.columns
            if not str(column).isdigit() or low <= int(column) <= high
        ]
    ]


__all__ = ["FilterValue", "Filters", "Selection", "SelectionError", "wire_text"]
