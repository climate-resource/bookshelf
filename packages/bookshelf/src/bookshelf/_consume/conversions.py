"""Converter rules shared by the synchronous and asynchronous resource handles.

These helpers hold the decisions that both transport surfaces make.
The handles themselves only choose how to fetch the data.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from bookshelf._consume.frames import filter_rows, filter_years, wide_timeseries
from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models

if TYPE_CHECKING:
    import pandas as pd
    from scmdata import ScmRun

_FRAME_TYPES = frozenset({models.ResourceType.timeseries, models.ResourceType.tabular})
_BYTE_READERS = ("fetch()", "as_path()")
_FRAME_READERS = ("as_df()", "as_polars()", "as_arrow()")
_TIMESERIES_READERS = ("as_df()", "as_long_df()", "as_scmrun()", "as_polars()", "as_arrow()")
_FRAME_EXPLORERS = ("query()", "facets()", "preview()")
_TIMESERIES_EXPLORERS = ("schema()",)

# What each resource type answers, so a handle describing itself names only calls that work.
_CAPABILITIES: dict[models.ResourceType | None, tuple[tuple[str, ...], tuple[str, ...]]] = {
    models.ResourceType.timeseries: (
        _TIMESERIES_READERS + _BYTE_READERS,
        _FRAME_EXPLORERS + _TIMESERIES_EXPLORERS,
    ),
    models.ResourceType.tabular: (_FRAME_READERS + _BYTE_READERS, _FRAME_EXPLORERS),
}
_NOTHING_BUT_BYTES = (_BYTE_READERS, ())


class UnsupportedConversionError(BookshelfError):
    """A converter does not apply to the resource type."""


def require_frame_support(resource_type: models.ResourceType) -> None:
    """Reject resource types that have no dataframe form."""
    if resource_type not in _FRAME_TYPES:
        raise UnsupportedConversionError(
            f"as_df() does not support {resource_type.value} resources"
        )


def require_timeseries_support(resource_type: models.ResourceType, caller: str) -> None:
    """Reject resource types that have no tidy timeseries form."""
    if resource_type is not models.ResourceType.timeseries:
        raise UnsupportedConversionError(f"{caller} requires a timeseries resource")


def readers_for(resource_type: models.ResourceType | None) -> tuple[str, ...]:
    """Name the converters that work on a resource type, for a handle describing itself."""
    return _CAPABILITIES.get(resource_type, _NOTHING_BUT_BYTES)[0]


def explorers_for(resource_type: models.ResourceType | None) -> tuple[str, ...]:
    """Name the book scoped exploration calls a resource type answers."""
    return _CAPABILITIES.get(resource_type, _NOTHING_BUT_BYTES)[1]


def shape_frame(resource_type: models.ResourceType, frame: pd.DataFrame) -> pd.DataFrame:
    """Return timeseries data in wide indexed form and leave other data untouched."""
    if resource_type is models.ResourceType.timeseries:
        return wide_timeseries(frame)
    return frame


_QUERY_ONLY_ARGUMENTS = ("select", "order", "drop_constant", "top_n", "limit", "offset")


def reject_query_arguments(filters: Mapping[str, str]) -> None:
    """Refuse server side arguments before a converter downloads anything."""
    passed = [name for name in _QUERY_ONLY_ARGUMENTS if name in filters]
    if passed:
        raise TypeError(f"converters filter locally, pass {', '.join(passed)} to query() instead")


def select_frame(
    resource_type: models.ResourceType,
    frame: pd.DataFrame,
    *,
    year_min: int | None,
    year_max: int | None,
    filters: Mapping[str, str],
) -> pd.DataFrame:
    """Shape a whole resource and apply the year window and filters locally."""
    if resource_type is not models.ResourceType.timeseries:
        if year_min is not None or year_max is not None:
            raise TypeError("year_min and year_max require a timeseries resource")
        return filter_rows(frame, filters)
    wide = filter_rows(wide_timeseries(frame), filters)
    return filter_years(wide, year_min=year_min, year_max=year_max)


def scmrun_class() -> type[ScmRun]:
    """Return the ScmRun class, reporting the missing optional extra as a conversion error."""
    try:
        from scmdata import ScmRun
    except ImportError as exc:
        raise UnsupportedConversionError(
            "as_scmrun() requires the 'scmrun' extra: pip install 'bookshelf[scmrun]'"
        ) from exc
    return ScmRun


def scmrun_converter() -> Callable[[pd.DataFrame], ScmRun]:
    """Return a converter from a wide indexed frame to an ScmRun.

    scmdata pivots long data and drops any timeseries whose values are all missing,
    so the constructor is handed the wide frame with its dimensions as columns.
    """
    run = scmrun_class()

    def convert(wide: pd.DataFrame) -> ScmRun:
        # A frame with no dimensions has only a positional index, which is not a column.
        return run(wide.reset_index(drop=all(name is None for name in wide.index.names)))

    return convert


__all__ = [
    "UnsupportedConversionError",
    "explorers_for",
    "readers_for",
    "reject_query_arguments",
    "require_frame_support",
    "require_timeseries_support",
    "scmrun_class",
    "scmrun_converter",
    "select_frame",
    "shape_frame",
]
