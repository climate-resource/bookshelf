"""Converter rules shared by the synchronous and asynchronous resource handles.

These helpers hold the decisions that both transport surfaces make.
The handles themselves only choose how to fetch the data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bookshelf._consume.frames import wide_timeseries
from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models

if TYPE_CHECKING:
    import pandas as pd
    from scmdata import ScmRun

_FRAME_TYPES = frozenset({models.ResourceType.timeseries, models.ResourceType.tabular})
_BYTE_READERS = ("fetch()", "as_path()")
_FRAME_READERS = ("as_df()", "as_polars()", "as_arrow()")
_TIMESERIES_READERS = ("as_df()", "as_long_df()", "as_scmrun()", "as_polars()", "as_arrow()")
_FRAME_EXPLORERS = ("facets()", "preview()")
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


def require_timeseries_support(resource_type: models.ResourceType) -> None:
    """Reject resource types that have no tidy timeseries form."""
    if resource_type is not models.ResourceType.timeseries:
        raise UnsupportedConversionError("as_long_df() requires a timeseries resource")


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


def scmrun_class() -> type[ScmRun]:
    """Return the ScmRun class, reporting the missing optional extra as a conversion error."""
    try:
        from scmdata import ScmRun
    except ImportError as exc:
        raise UnsupportedConversionError(
            "as_scmrun() requires the 'scmrun' extra: pip install 'bookshelf[scmrun]'"
        ) from exc
    return ScmRun


__all__ = [
    "UnsupportedConversionError",
    "explorers_for",
    "readers_for",
    "require_frame_support",
    "require_timeseries_support",
    "scmrun_class",
    "shape_frame",
]
