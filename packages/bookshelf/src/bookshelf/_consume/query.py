"""Typed timeseries query preparation shared by both transport surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from bookshelf._generated import models


@dataclass(frozen=True, slots=True)
class TimeseriesQuery:
    """Parsed book timeseries controls and resource filters."""

    filters: dict[str, str]
    year_min: int | None
    year_max: int | None
    top_n: int | None
    drop_constant: bool

    @classmethod
    def parse(cls, values: Mapping[str, str]) -> TimeseriesQuery:
        filters = dict(values)
        year_min = filters.pop("year_min", None)
        year_max = filters.pop("year_max", None)
        top_n = filters.pop("top_n", None)
        drop_constant = filters.pop("drop_constant", "false") == "true"
        return cls(
            filters=filters,
            year_min=int(year_min) if year_min is not None else None,
            year_max=int(year_max) if year_max is not None else None,
            top_n=int(top_n) if top_n is not None else None,
            drop_constant=drop_constant,
        )

    def facet_filters(self) -> dict[str, str]:
        """Return data filters plus the selected year window."""
        filters = dict(self.filters)
        if self.year_min is not None:
            filters["year.min"] = str(self.year_min)
        if self.year_max is not None:
            filters["year.max"] = str(self.year_max)
        return filters


def timeseries_filters(
    filters: Mapping[str, str],
    *,
    year_min: int | None,
    year_max: int | None,
    drop_constant: bool,
    top_n: int | None,
) -> dict[str, str]:
    """Encode the book entry trimming controls alongside the resource filters.

    This is the inverse of :meth:`TimeseriesQuery.parse`.
    """
    encoded = dict(filters)
    if year_min is not None:
        encoded["year_min"] = str(year_min)
    if year_max is not None:
        encoded["year_max"] = str(year_max)
    if drop_constant:
        encoded["drop_constant"] = "true"
    if top_n is not None:
        encoded["top_n"] = str(top_n)
    return encoded


def constant_columns(facets: models.FacetsResponse) -> list[str]:
    """Return the columns that hold a single value across the filtered data."""
    return [facet.column for facet in facets.facets if facet.total_unique == 1]


__all__ = ["TimeseriesQuery", "constant_columns", "timeseries_filters"]
