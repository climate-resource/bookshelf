"""The read decisions both handle flavours share, kept free of I/O.

A handle fetches either the cached file or a ``/data`` response,
and hands it here to be checked, selected, shaped and summarised.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
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
from bookshelf._consume.frames import drop_constant_dimensions
from bookshelf._consume.selection import Selection, SelectionError
from bookshelf._core.errors import ValidationError
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

    @property
    def complete(self) -> bool:
        """Whether ``data`` holds every row the selection matches."""
        return self.completeness == "complete"


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


def check_frame_read(resource_type: models.ResourceType, selection: Selection, caller: str) -> None:
    """Refuse a read the resource type cannot answer, before anything is fetched."""
    require_frame_support(resource_type, caller)
    selection.check(resource_type)


def check_timeseries_read(resource_type: models.ResourceType, caller: str) -> None:
    require_timeseries_support(resource_type, caller)


def settle(
    resource_type: models.ResourceType,
    frame: pd.DataFrame,
    selection: Selection | None,
) -> pd.DataFrame:
    """Shape a fetched frame, applying the selection when the platform has not already."""
    shaped = shape_frame(resource_type, frame)
    return shaped if selection is None else selection.apply(shaped)


def order_param(order: str | Sequence[str] | None) -> str | None:
    """Encode column names, each prefixed with ``-`` to sort it descending."""
    if order is None:
        return None
    keys = [order] if isinstance(order, str) else list(order)
    return ",".join(f"{key[1:]}.desc" if key.startswith("-") else f"{key}.asc" for key in keys)


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
    drop_constant: bool,
) -> None:
    check_frame_read(resource_type, selection, "preview()")
    if limit < 1:
        raise SelectionError("limit must be at least 1")
    if drop_constant and resource_type is not models.ResourceType.timeseries:
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
    except ValidationError as exc:
        raise SelectionError(exc.detail) from exc


__all__ = [
    "DataPreview",
    "ResourceInfo",
    "check_frame_read",
    "check_preview",
    "check_timeseries_read",
    "order_param",
    "preview_params",
    "selection_rejections",
    "settle",
    "settle_preview",
]
