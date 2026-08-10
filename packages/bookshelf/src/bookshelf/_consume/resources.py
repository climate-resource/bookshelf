"""Typed resource handles for consuming Bookshelf resources.

Each handle comes in a synchronous and an asynchronous flavour.
The two differ only in how they reach the transport.
Every decision they share lives in the sibling modules, so the flavours cannot drift apart.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from bookshelf._consume.conversions import (
    UnsupportedConversionError,
    require_frame_support,
    require_timeseries_support,
    scmrun_class,
    shape_frame,
)
from bookshelf._consume.frames import (
    arrow_converter,
    long_timeseries,
    polars_converter,
    timeseries_frame,
)
from bookshelf._consume.integrity import cached_if_verified, require_cached, verify_path
from bookshelf._consume.presentation import summary_table
from bookshelf._consume.query import TimeseriesQuery, constant_columns, timeseries_filters
from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf.cache import ContentCache

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa
    from scmdata import ScmRun

_FACET_MAX_VALUES = 500
_TRIMMING_ON_RESOURCE = "timeseries trimming requires a book entry handle"
_UNSUPPORTED_TIMESERIES_ARGS = "timeseries entries accept filters, trimming, top_n, and limit"


class _ResourceHandle:
    """Identity and lazily resolved metadata shared by both resource flavours."""

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        tracking_id: str | UUID,
        *,
        metadata: models.ResourceRead | None = None,
        resource_type: models.ResourceType | None = None,
    ) -> None:
        if resource_type is None and metadata is not None:
            resource_type = metadata.type
        self._client = client
        self._cache = cache
        self.tracking_id = UUID(str(tracking_id))
        self._metadata = metadata
        self._resource_type = resource_type


class Resource(_ResourceHandle):
    """Lean immutable resource handle for machine and provenance reads."""

    @property
    def metadata(self) -> models.ResourceRead:
        """Return the generated resource projection."""
        if self._metadata is None:
            self._metadata = self._client.get_resource(self.tracking_id)
            self._resource_type = self._metadata.type
        return self._metadata

    @property
    def type(self) -> models.ResourceType:
        """Return the canonical resource type."""
        if self._resource_type is None:
            return self.metadata.type
        return self._resource_type

    def _repr_html_(self) -> str:
        metadata = self.metadata
        return summary_table(
            "Bookshelf Resource",
            {
                "tracking_id": self.tracking_id,
                "type": metadata.type.value,
                "hash": metadata.hash,
                "visibility": metadata.visibility.value,
            },
        )

    def _frame(
        self,
        *,
        select: str | None,
        order: str | None,
        limit: int | None,
        offset: int | None,
        filters: Mapping[str, str],
    ) -> pd.DataFrame:
        return self._client.query_resource_dataframe(
            self.tracking_id,
            select=select,
            order=order,
            limit=limit,
            offset=offset,
            filters=filters,
        )

    def _dataframe(
        self,
        *,
        select: str | None,
        order: str | None,
        limit: int | None,
        offset: int | None,
        filters: Mapping[str, str],
    ) -> pd.DataFrame:
        resource_type = self.type
        require_frame_support(resource_type)
        frame = self._frame(
            select=select,
            order=order,
            limit=limit,
            offset=offset,
            filters=filters,
        )
        return shape_frame(resource_type, frame)

    def as_df(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        drop_constant: bool = False,
        top_n: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> pd.DataFrame:
        """Return pandas data, using wide indexed form for timeseries."""
        if year_min is not None or year_max is not None or drop_constant or top_n is not None:
            raise TypeError(_TRIMMING_ON_RESOURCE)
        return self._dataframe(
            select=select,
            order=order,
            limit=limit,
            offset=offset,
            filters=filters,
        )

    def as_long_df(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> pd.DataFrame:
        """Return tidy pandas timeseries data."""
        require_timeseries_support(self.type)
        return long_timeseries(
            self._frame(
                select=select,
                order=order,
                limit=limit,
                offset=offset,
                filters=filters,
            )
        )

    def as_polars(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> pl.DataFrame:
        """Return the resource as a Polars DataFrame."""
        convert = polars_converter()
        return convert(
            self._dataframe(
                select=select,
                order=order,
                limit=limit,
                offset=offset,
                filters=filters,
            )
        )

    def as_arrow(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> pa.Table:
        """Return the resource as a PyArrow table."""
        convert = arrow_converter()
        return convert(
            self._dataframe(
                select=select,
                order=order,
                limit=limit,
                offset=offset,
                filters=filters,
            )
        )

    def as_scmrun(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> ScmRun:
        """Return timeseries data as an scmdata ScmRun."""
        run = scmrun_class()
        return run(
            self.as_long_df(
                select=select,
                order=order,
                limit=limit,
                offset=offset,
                **filters,
            )
        )

    def fetch(self) -> bytes:
        """Return verified bytes, using memory proportional to the resource size.

        Use :meth:`as_path` to stream large resources without loading them into memory.
        """
        return self._ensure_cached().read_bytes()

    def as_path(self) -> Path:
        """Stream and verify the resource, then return its cached path."""
        return self._ensure_cached()

    def _ensure_cached(self) -> Path:
        content_hash = self.metadata.hash
        cached = cached_if_verified(self._cache, content_hash)
        if cached is not None:
            return cached
        download = self._client.get_resource_download(self.tracking_id)
        with self._cache.stage(content_hash) as temporary:
            self._client.stream_url_to_path(download.presigned_url, temporary)
            verify_path(temporary, content_hash)
        return require_cached(self._cache, content_hash)


class BookEntry(Resource):
    """A resource handle with its book scoped exploration capabilities."""

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        book_id: str | UUID,
        entry: models.BookEntryItem,
    ) -> None:
        super().__init__(client, cache, entry.tracking_id, resource_type=entry.type)
        self.book_id = UUID(str(book_id))
        self.entry = entry
        self.name_in_book = entry.name_in_book

    def as_df(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        drop_constant: bool = False,
        top_n: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> pd.DataFrame:
        """Return book scoped data with optional server side timeseries trimming."""
        return self._dataframe(
            select=select,
            order=order,
            limit=limit,
            offset=offset,
            filters=timeseries_filters(
                filters,
                year_min=year_min,
                year_max=year_max,
                drop_constant=drop_constant,
                top_n=top_n,
            ),
        )

    def _frame(
        self,
        *,
        select: str | None,
        order: str | None,
        limit: int | None,
        offset: int | None,
        filters: Mapping[str, str],
    ) -> pd.DataFrame:
        if self.type is not models.ResourceType.timeseries:
            return super()._frame(
                select=select,
                order=order,
                limit=limit,
                offset=offset,
                filters=filters,
            )
        if select is not None or order is not None or offset is not None:
            raise TypeError(_UNSUPPORTED_TIMESERIES_ARGS)
        query = TimeseriesQuery.parse(filters)
        drops: list[str] = []
        if query.drop_constant:
            facets = self._client.get_book_resource_facets(
                self.book_id,
                self.name_in_book,
                max_values=_FACET_MAX_VALUES,
                filters=query.facet_filters(),
            )
            drops = constant_columns(facets)
        response = self._client.get_book_resource_timeseries(
            self.book_id,
            self.name_in_book,
            drop=drops,
            limit=limit,
            top_n=query.top_n,
            year_min=query.year_min,
            year_max=query.year_max,
            filters=query.filters,
        )
        return timeseries_frame(response)

    def _repr_html_(self) -> str:
        return summary_table(
            "Bookshelf Book Entry",
            {
                "name": self.name_in_book,
                "tracking_id": self.tracking_id,
                "type": self.type.value,
                "book_id": self.book_id,
            },
        )

    def as_resource(self) -> Resource:
        """Drop book context and return the lean resource handle."""
        return Resource(
            self._client,
            self._cache,
            self.tracking_id,
            metadata=self._metadata,
            resource_type=self._resource_type,
        )

    def facets(
        self, *, max_values: int = _FACET_MAX_VALUES, **filters: str
    ) -> models.FacetsResponse:
        """Return book scoped facet values."""
        return self._client.get_book_resource_facets(
            self.book_id,
            self.name_in_book,
            max_values=max_values,
            filters=filters,
        )

    def preview(self, *, limit: int = 100, offset: int = 0) -> models.PreviewResponse:
        """Return a book scoped tabular preview."""
        return self._client.get_book_resource_preview(
            self.book_id,
            self.name_in_book,
            limit=limit,
            offset=offset,
        )

    def schema(self, *, limit: int = 100, offset: int = 0) -> models.TimeseriesMetadataResponse:
        """Return book scoped timeseries schema metadata."""
        return self._client.get_book_resource_schema(
            self.book_id,
            self.name_in_book,
            limit=limit,
            offset=offset,
        )


class AsyncResource(_ResourceHandle):
    """Asynchronous lean immutable resource handle."""

    async def _get_metadata(self) -> models.ResourceRead:
        if self._metadata is None:
            self._metadata = await self._client.get_resource_async(self.tracking_id)
            self._resource_type = self._metadata.type
        return self._metadata

    async def _get_type(self) -> models.ResourceType:
        if self._resource_type is None:
            return (await self._get_metadata()).type
        return self._resource_type

    def _repr_html_(self) -> str:
        resource_type = self._resource_type.value if self._resource_type is not None else "unknown"
        return summary_table(
            "Bookshelf Async Resource",
            {"tracking_id": self.tracking_id, "type": resource_type},
        )

    async def _frame(
        self,
        *,
        select: str | None,
        order: str | None,
        limit: int | None,
        offset: int | None,
        filters: Mapping[str, str],
    ) -> pd.DataFrame:
        return await self._client.query_resource_dataframe_async(
            self.tracking_id,
            select=select,
            order=order,
            limit=limit,
            offset=offset,
            filters=filters,
        )

    async def _dataframe(
        self,
        *,
        select: str | None,
        order: str | None,
        limit: int | None,
        offset: int | None,
        filters: Mapping[str, str],
    ) -> pd.DataFrame:
        resource_type = await self._get_type()
        require_frame_support(resource_type)
        frame = await self._frame(
            select=select,
            order=order,
            limit=limit,
            offset=offset,
            filters=filters,
        )
        return shape_frame(resource_type, frame)

    async def as_df(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        drop_constant: bool = False,
        top_n: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> pd.DataFrame:
        """Return pandas data, using wide indexed form for timeseries."""
        if year_min is not None or year_max is not None or drop_constant or top_n is not None:
            raise TypeError(_TRIMMING_ON_RESOURCE)
        return await self._dataframe(
            select=select,
            order=order,
            limit=limit,
            offset=offset,
            filters=filters,
        )

    async def as_long_df(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> pd.DataFrame:
        """Return tidy pandas timeseries data."""
        require_timeseries_support(await self._get_type())
        return long_timeseries(
            await self._frame(
                select=select,
                order=order,
                limit=limit,
                offset=offset,
                filters=filters,
            )
        )

    async def as_polars(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> pl.DataFrame:
        """Return the resource as a Polars DataFrame."""
        convert = polars_converter()
        return convert(
            await self._dataframe(
                select=select,
                order=order,
                limit=limit,
                offset=offset,
                filters=filters,
            )
        )

    async def as_arrow(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> pa.Table:
        """Return the resource as a PyArrow table."""
        convert = arrow_converter()
        return convert(
            await self._dataframe(
                select=select,
                order=order,
                limit=limit,
                offset=offset,
                filters=filters,
            )
        )

    async def as_scmrun(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> ScmRun:
        """Return timeseries data as an scmdata ScmRun."""
        run = scmrun_class()
        return run(
            await self.as_long_df(
                select=select,
                order=order,
                limit=limit,
                offset=offset,
                **filters,
            )
        )

    async def fetch(self) -> bytes:
        """Return verified bytes, using memory proportional to the resource size.

        Use :meth:`as_path` to stream large resources without loading them into memory.
        """
        path = await self._ensure_cached()
        return await asyncio.to_thread(path.read_bytes)

    async def as_path(self) -> Path:
        """Stream and verify the resource, then return its cached path."""
        return await self._ensure_cached()

    async def _ensure_cached(self) -> Path:
        content_hash = (await self._get_metadata()).hash
        # A cache hit hashes the whole file on disk, so run it off the event loop.
        cached = await asyncio.to_thread(cached_if_verified, self._cache, content_hash)
        if cached is not None:
            return cached
        download = await self._client.get_resource_download_async(self.tracking_id)
        with self._cache.stage(content_hash) as temporary:
            await self._client.stream_url_to_path_async(download.presigned_url, temporary)
            # Verification hashes the whole downloaded file, so run it off the event loop too.
            await asyncio.to_thread(verify_path, temporary, content_hash)
        return require_cached(self._cache, content_hash)


class AsyncBookEntry(AsyncResource):
    """An async resource handle with book scoped exploration capabilities."""

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        book_id: str | UUID,
        entry: models.BookEntryItem,
    ) -> None:
        super().__init__(client, cache, entry.tracking_id, resource_type=entry.type)
        self.book_id = UUID(str(book_id))
        self.entry = entry
        self.name_in_book = entry.name_in_book

    async def as_df(
        self,
        *,
        select: str | None = None,
        order: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        drop_constant: bool = False,
        top_n: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **filters: str,
    ) -> pd.DataFrame:
        """Return book scoped data with optional server side timeseries trimming."""
        return await self._dataframe(
            select=select,
            order=order,
            limit=limit,
            offset=offset,
            filters=timeseries_filters(
                filters,
                year_min=year_min,
                year_max=year_max,
                drop_constant=drop_constant,
                top_n=top_n,
            ),
        )

    async def _frame(
        self,
        *,
        select: str | None,
        order: str | None,
        limit: int | None,
        offset: int | None,
        filters: Mapping[str, str],
    ) -> pd.DataFrame:
        if await self._get_type() is not models.ResourceType.timeseries:
            return await super()._frame(
                select=select,
                order=order,
                limit=limit,
                offset=offset,
                filters=filters,
            )
        if select is not None or order is not None or offset is not None:
            raise TypeError(_UNSUPPORTED_TIMESERIES_ARGS)
        query = TimeseriesQuery.parse(filters)
        drops: list[str] = []
        if query.drop_constant:
            facets = await self._client.get_book_resource_facets_async(
                self.book_id,
                self.name_in_book,
                max_values=_FACET_MAX_VALUES,
                filters=query.facet_filters(),
            )
            drops = constant_columns(facets)
        response = await self._client.get_book_resource_timeseries_async(
            self.book_id,
            self.name_in_book,
            drop=drops,
            limit=limit,
            top_n=query.top_n,
            year_min=query.year_min,
            year_max=query.year_max,
            filters=query.filters,
        )
        return timeseries_frame(response)

    def _repr_html_(self) -> str:
        # Read the handle's own type, not the entry's.
        # A book entry may arrive without one, and only the handle learns it from the metadata.
        resource_type = self._resource_type.value if self._resource_type is not None else "unknown"
        return summary_table(
            "Bookshelf Async Book Entry",
            {
                "name": self.name_in_book,
                "tracking_id": self.tracking_id,
                "type": resource_type,
                "book_id": self.book_id,
            },
        )

    def as_resource(self) -> AsyncResource:
        """Drop book context and return the lean async resource handle."""
        return AsyncResource(
            self._client,
            self._cache,
            self.tracking_id,
            metadata=self._metadata,
            resource_type=self._resource_type,
        )

    async def facets(
        self, *, max_values: int = _FACET_MAX_VALUES, **filters: str
    ) -> models.FacetsResponse:
        """Return book scoped facet values."""
        return await self._client.get_book_resource_facets_async(
            self.book_id,
            self.name_in_book,
            max_values=max_values,
            filters=filters,
        )

    async def preview(self, *, limit: int = 100, offset: int = 0) -> models.PreviewResponse:
        """Return a book scoped tabular preview."""
        return await self._client.get_book_resource_preview_async(
            self.book_id,
            self.name_in_book,
            limit=limit,
            offset=offset,
        )

    async def schema(
        self, *, limit: int = 100, offset: int = 0
    ) -> models.TimeseriesMetadataResponse:
        """Return book scoped timeseries schema metadata."""
        return await self._client.get_book_resource_schema_async(
            self.book_id,
            self.name_in_book,
            limit=limit,
            offset=offset,
        )


__all__ = [
    "AsyncBookEntry",
    "AsyncResource",
    "BookEntry",
    "Resource",
    "UnsupportedConversionError",
]
