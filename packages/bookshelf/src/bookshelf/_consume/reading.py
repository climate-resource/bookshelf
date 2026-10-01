"""The read decisions both handle flavours share, kept free of I/O.

A handle fetches either the cached file or a ``/data`` response,
and hands it here to be checked, selected, shaped and summarised.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from bookshelf._consume.conversions import (
    UnsupportedConversionError,
    readers_for,
    require_frame_support,
    require_timeseries_support,
    shape_frame,
)
from bookshelf._consume.frames import drop_constant_dimensions, is_year_column
from bookshelf._consume.selection import Selection
from bookshelf._core.errors import RequestValidationError, SelectionError
from bookshelf._generated import models

if TYPE_CHECKING:
    import pandas as pd

type Completeness = Literal["complete", "partial"]


@dataclass(frozen=True, slots=True)
class DataPreview:
    """A bounded look at a selection, saying whether it holds every selected row.

    A wide timeseries row is one series, so ``limit`` counts series rather than observations.
    """

    data: pd.DataFrame
    completeness: Completeness
    """Whether ``data`` holds every row the request matches, after any ``top_n``."""


@dataclass(frozen=True, slots=True)
class ResourceInfo:
    """What the platform records about a resource, and the reads its type answers."""

    tracking_id: UUID
    type: models.ResourceType
    hash: str
    visibility: models.Visibility
    readers: tuple[str, ...]
    record: models.ResourceRead
    """The full projection the platform returned."""

    @classmethod
    def from_record(cls, record: models.ResourceRead) -> ResourceInfo:
        return cls(
            tracking_id=record.tracking_id,
            type=record.type,
            hash=record.hash,
            visibility=record.visibility,
            readers=readers_for(record.type),
            record=record,
        )


def check_frame_read(
    resource_type: models.ResourceType,
    selection: Selection,
    caller: str,
    *,
    timeseries_only: bool = False,
) -> None:
    """Refuse a read the resource type cannot answer, before anything is fetched."""
    if timeseries_only:
        require_timeseries_support(resource_type, caller)
    require_frame_support(resource_type, caller)
    selection.check(resource_type)


def settle_cached(
    resource_type: models.ResourceType, frame: pd.DataFrame, selection: Selection
) -> pd.DataFrame:
    """Shape the cached file and apply the selection to it."""
    import pandas as pd

    shaped = shape_frame(resource_type, frame)
    selected = selection.apply(shaped)
    # pyarrow numbers the rows it filtered afresh, so rows pandas filtered are renumbered too.
    return selected.reset_index(drop=True) if isinstance(shaped.index, pd.RangeIndex) else selected


def settle_selected(
    resource_type: models.ResourceType, frame: pd.DataFrame, selection: Selection
) -> pd.DataFrame:
    """Shape rows the platform selected, and order them here.

    The platform names wide year columns by their stored label, so it cannot order by a shaped one.
    """
    return selection.sort(shape_frame(resource_type, frame))


def preview_params(selection: Selection, *, top_n: int | None) -> dict[str, str]:
    params = selection.data_params()
    if top_n is not None:
        params["$top_n"] = str(top_n)
    return params


def check_preview(
    resource_type: models.ResourceType,
    selection: Selection,
    *,
    limit: int,
    top_n: int | None,
    drop_constant: bool,
) -> None:
    check_frame_read(resource_type, selection, "preview()")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    # The platform reads top_n alongside an order as "the first n in that order", not a ranking.
    if top_n is not None and selection.order:
        raise ValueError("top_n ranks by the latest value, so it cannot take an order as well")
    timeseries = resource_type is models.ResourceType.timeseries
    if timeseries and any(is_year_column(column) for column, _ in selection.order):
        raise ValueError("preview() orders by dimension columns, so sort a complete read by year")
    if drop_constant and not timeseries:
        raise UnsupportedConversionError("drop_constant requires a timeseries resource")


def settle_preview(
    resource_type: models.ResourceType,
    frame: pd.DataFrame,
    *,
    limit: int,
    drop_constant: bool,
) -> DataPreview:
    """Cut a response fetched with one row beyond the limit, so a longer one proves more exist."""
    shaped = shape_frame(resource_type, frame)
    completeness: Completeness = "partial" if len(shaped) > limit else "complete"
    shaped = shaped.iloc[:limit]
    if drop_constant:
        shaped = drop_constant_dimensions(shaped)
    return DataPreview(data=shaped, completeness=completeness)


@contextmanager
def selection_rejections() -> Iterator[None]:
    """Report the platform refusing a selection as the same error a local read raises."""
    try:
        yield
    except RequestValidationError as exc:
        raise SelectionError(exc.detail) from exc


__all__ = [
    "DataPreview",
    "ResourceInfo",
    "check_frame_read",
    "check_preview",
    "preview_params",
    "selection_rejections",
    "settle_cached",
    "settle_selected",
    "settle_preview",
]
