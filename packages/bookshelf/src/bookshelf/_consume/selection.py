"""The one selection language every read takes, and its two executions.

A selection is the same whether the rows are picked from the cached file or by the platform,
so this module owns its validation, its local matching and its wire encoding.
"""

from __future__ import annotations

import math
import operator
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from bookshelf._consume.frames import is_year_column, year_label
from bookshelf._core.errors import SelectionError
from bookshelf._core.frames import ParquetScan
from bookshelf._generated import models

if TYPE_CHECKING:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.compute as pc

type FilterValue = str | int | float | bool | None
type Filters = Mapping[str, FilterValue | Iterable[FilterValue]]
type Order = str | Sequence[str]

_TRUE_WORDS = frozenset({"true", "1", "yes"})


def native_scalar(value: object) -> object:
    """Unwrap a numpy scalar, such as one taken from a frame, to the Python value it holds."""
    if type(value).__module__ == "numpy" and getattr(value, "ndim", None) == 0:
        return value.item()  # type: ignore[attr-defined]
    return value


def positive_int(name: str, value: object) -> int:
    """Return a count or edition as an int, refusing a bool, a fraction or anything below 1."""
    value = native_scalar(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be a whole number, not {value!r}")
    if value < 1:
        raise ValueError(f"{name} must be at least 1, not {value}")
    return value


def _scalar(column: str, value: object) -> FilterValue:
    value = native_scalar(value)
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise TypeError(f"filter {column!r} has a {type(value).__name__} value, not a scalar")


def _values(column: str, wanted: object) -> tuple[FilterValue, ...]:
    wanted = native_scalar(wanted)
    if isinstance(wanted, str | bytes | Mapping) or not isinstance(wanted, Iterable):
        return (_scalar(column, wanted),)
    if getattr(wanted, "ndim", 1) > 1:
        raise TypeError(f"filter {column!r} has a {type(wanted).__name__} value, not a list")
    values = tuple(_scalar(column, value) for value in wanted)
    if isinstance(wanted, AbstractSet):
        # A set's order varies between processes, so sort it to keep the selection stable.
        values = tuple(sorted(values, key=lambda value: (type(value).__name__, str(value))))
    if not values:
        raise ValueError(f"filter {column!r} lists no values, so it would select nothing")
    if len(values) > 1 and (None in values or "" in values):
        raise ValueError(f"filter {column!r} can match a missing or empty value only on its own")
    return values


def wire_text(value: FilterValue) -> str:
    """Spell a filter value the way the platform reads it back."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _year_bound(name: str, bound: object) -> int | None:
    if bound is None:
        return None
    bound = native_scalar(bound)
    if isinstance(bound, bool):
        raise TypeError(f"{name} must be an integer year")
    try:
        return operator.index(bound)  # type: ignore[arg-type]
    except TypeError:
        raise TypeError(f"{name} must be an integer year") from None


def _escaped(value: FilterValue) -> str:
    return wire_text(value).replace("\\", "\\\\").replace(",", "\\,")


@dataclass(frozen=True, slots=True)
class Selection:
    """Validated filters, an inclusive year window and a row order.

    Values within one filter are alternatives, and separate filters must all hold.
    Each order key is a column name and whether it sorts descending.
    """

    filters: tuple[tuple[str, tuple[FilterValue, ...]], ...] = ()
    year_min: int | None = None
    year_max: int | None = None
    order: tuple[tuple[str, bool], ...] = ()

    @classmethod
    def build(
        cls,
        filters: Filters | None,
        *,
        year_min: int | None,
        year_max: int | None,
        order: Order | None = None,
    ) -> Selection:
        """Validate a caller's selection before anything is fetched."""
        if filters is not None and not isinstance(filters, Mapping):
            raise TypeError("filters must be a mapping of column name to value or values")
        normalised = sorted(
            (str(column), _values(str(column), wanted))
            for column, wanted in (filters or {}).items()
        )
        return cls(
            tuple(normalised),
            _year_bound("year_min", year_min),
            _year_bound("year_max", year_max),
            _order_keys(order),
        )

    @property
    def has_years(self) -> bool:
        return self.year_min is not None or self.year_max is not None

    def check(self, resource_type: models.ResourceType) -> None:
        """Refuse a year window on data that has no year columns."""
        if self.has_years and resource_type is not models.ResourceType.timeseries:
            raise TypeError("year_min and year_max need a timeseries resource")

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
                raise ValueError(f"book routes cannot filter {column!r} on a missing value")
            texts = [wire_text(value) for value in values]
            params[column] = texts[0] if len(texts) == 1 else texts
        return params

    def order_param(self) -> str | None:
        """Encode the order for the ``/data`` route."""
        if not self.order:
            return None
        return ",".join(f"{column}.{'desc' if desc else 'asc'}" for column, desc in self.order)

    def parquet_scan(self, resource_type: models.ResourceType, schema: pa.Schema) -> ParquetScan:
        """Plan the part of the selection pyarrow can apply while reading a stored parquet file.

        Only what provably keeps every row and column :meth:`apply` would is planned,
        so :meth:`apply` still runs afterwards and stays the one definition of a match.
        """
        timeseries = resource_type is models.ResourceType.timeseries
        # A long file pivots after reading, so dropping rows first could drop whole year columns.
        if timeseries and {"year", "value"} <= set(schema.names):
            return ParquetScan()
        filtered = {column for column, _ in self.filters}
        columns = None
        if timeseries and self.has_years:
            low, high = _year_bounds(self.year_min, self.year_max)
            labels = {name: year_label(name) for name in schema.names}
            columns = [
                name
                for name, label in labels.items()
                if not is_year_column(label) or label in filtered or low <= int(label) <= high
            ]
        rows = None
        for column, values in self.filters:
            # A missing or repeated name is left for apply() to report.
            if schema.get_field_index(column) < 0:
                continue
            if timeseries and is_year_column(year_label(column)):
                continue
            condition = _parquet_match(column, schema.field(column).type, values)
            if condition is not None:
                rows = condition if rows is None else rows & condition
        dictionary = _dictionary_columns(schema, self.filters) if timeseries else None
        return ParquetScan(columns=columns, rows=rows, dictionary=dictionary)

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Pick the selected rows and year columns out of a shaped frame, then order them."""
        selected = _filter_years(_filter_rows(frame, self.filters), self.year_min, self.year_max)
        return self.sort(selected)

    def sort(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Order a shaped frame, with missing values first either way, as the platform does."""
        return _sorted(frame, self.order)


def _parquet_match(
    column: str, data_type: pa.DataType, values: tuple[FilterValue, ...]
) -> pc.Expression | None:
    """Match one filter in pyarrow, or ``None`` where pandas' reading of the value could differ."""
    import pyarrow.compute as pc

    field = pc.field(column)
    if values == (None,):
        return field.is_null(nan_is_null=True)
    if _is_text(data_type):
        return field.isin([wire_text(value) for value in values])
    return None


def _dictionary_columns(
    schema: pa.Schema, filters: tuple[tuple[str, tuple[FilterValue, ...]], ...]
) -> list[str] | None:
    """Name the text dimensions a wide file can build its index from as dictionary codes.

    A single dimension makes a flat index, which ``set_index`` builds cheaply.
    pandas metadata or a stored dictionary would make pandas pick a dtype the codes cannot reproduce,
    and repeated labels leave the frame to ``set_index``.
    """
    import pyarrow as pa

    dimensions = [field for field in schema if not is_year_column(year_label(field.name))]
    if len(dimensions) < 2 or schema.pandas_metadata is not None:
        return None
    if len({year_label(name) for name in schema.names}) < len(schema.names):
        return None
    if any(pa.types.is_dictionary(field.type) for field in dimensions):
        return None
    # pyarrow skips null-only row groups of a dictionary column filtered on being null.
    null_matched = {column for column, values in filters if values == (None,)}
    names = [
        field.name
        for field in dimensions
        if _is_text(field.type) and field.name not in null_matched
    ]
    return names or None


def _is_text(data_type: pa.DataType) -> bool:
    import pyarrow as pa

    types = pa.types
    if types.is_dictionary(data_type):
        data_type = data_type.value_type
    return bool(types.is_string(data_type) or types.is_large_string(data_type))


def _order_keys(order: Order | None) -> tuple[tuple[str, bool], ...]:
    if order is None:
        return ()
    keys = [order] if isinstance(order, str) else list(order)
    if not all(isinstance(key, str) and key.lstrip("-") for key in keys):
        raise ValueError("order takes column names, each prefixed with '-' to sort descending")
    return tuple((key[1:], True) if key.startswith("-") else (key, False) for key in keys)


def _sorted(frame: pd.DataFrame, order: tuple[tuple[str, bool], ...]) -> pd.DataFrame:
    if not order:
        return frame
    try:
        return frame.sort_values(
            by=[column for column, _ in order],
            ascending=[not desc for _, desc in order],
            na_position="first",
            kind="stable",
        )
    except KeyError as exc:
        raise SelectionError(f"cannot order by {exc.args[0]!r}, it is not a column") from exc


def _matches(column: str, values: pd.Series[Any] | pd.Index[Any], wanted: FilterValue) -> Any:
    """Compare as the platform does, reading the wanted value as the column's type."""
    import pandas as pd
    from pandas.api.types import is_bool_dtype, is_integer_dtype, is_numeric_dtype

    series = pd.Series(values)
    if wanted is None:
        return series.isna().to_numpy(dtype=bool)
    if is_bool_dtype(series.dtype):
        flag = wanted if isinstance(wanted, bool) else wire_text(wanted).lower() in _TRUE_WORDS
        return (series == flag).fillna(False).to_numpy(dtype=bool)
    if is_numeric_dtype(series.dtype):
        read = int if is_integer_dtype(series.dtype) else float
        try:
            number = read(wire_text(wanted))
        except ValueError:
            raise SelectionError(
                f"filter {column!r} holds {series.dtype} values, which {wanted!r} is not"
            ) from None
        return (series == number).fillna(False).to_numpy(dtype=bool)
    return (series.notna() & (series.astype(str) == wire_text(wanted))).to_numpy(dtype=bool)


def _filter_rows(
    frame: pd.DataFrame, filters: tuple[tuple[str, tuple[FilterValue, ...]], ...]
) -> pd.DataFrame:
    import numpy as np

    if not filters:
        return frame
    names = [name for name in frame.index.names if name is not None]
    mask = np.ones(len(frame), dtype=bool)
    for column, values in filters:
        source: pd.Series[Any] | pd.Index[Any]
        if column in frame.columns:
            source = frame[column]
        elif column in names:
            source = frame.index.get_level_values(column)
        else:
            raise unknown_filter_column(column, frame)
        either = np.zeros(len(frame), dtype=bool)
        for wanted in values:
            either |= _matches(column, source, wanted)
        mask &= either
    # A filter that keeps every row, such as region World on a global file, need not copy it.
    return frame if mask.all() else frame[mask]


def unknown_filter_column(column: str, frame: pd.DataFrame) -> SelectionError:
    """Name the columns a shaped frame can be filtered on, for a filter that named another."""
    names = [name for name in frame.index.names if name is not None]
    columns = [column for column in frame.columns if not is_year_column(column)]
    known = ", ".join(map(str, [*names, *columns]))
    return SelectionError(f"cannot filter on {column!r}, the columns are: {known}")


def _year_bounds(year_min: int | None, year_max: int | None) -> tuple[float, float]:
    low = year_min if year_min is not None else -math.inf
    high = year_max if year_max is not None else math.inf
    return low, high


def _filter_years(wide: pd.DataFrame, year_min: int | None, year_max: int | None) -> pd.DataFrame:
    if year_min is None and year_max is None:
        return wide
    low, high = _year_bounds(year_min, year_max)
    kept = [
        column
        for column in wide.columns
        if not is_year_column(column) or low <= int(column) <= high
    ]
    return wide if len(kept) == len(wide.columns) else wide[kept]


__all__ = [
    "FilterValue",
    "Filters",
    "Order",
    "Selection",
    "native_scalar",
    "positive_int",
    "unknown_filter_column",
]
