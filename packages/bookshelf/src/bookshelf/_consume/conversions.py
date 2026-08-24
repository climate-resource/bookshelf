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
    "require_frame_support",
    "require_timeseries_support",
    "scmrun_class",
    "shape_frame",
]
