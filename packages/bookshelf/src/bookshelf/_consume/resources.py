"""Typed resource handles for consuming Bookshelf resources.

Each handle comes in a synchronous and an asynchronous flavour.
The two differ only in how they reach the transport.
Every decision they share lives in the sibling modules, so the flavours cannot drift apart.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import bookshelf._records as records
from bookshelf._consume.conversions import (
    explorers_for,
    readers_for,
    scmrun_class,
    shape_frame,
)
from bookshelf._consume.frames import (
    arrow_converter,
    int_year_columns,
    legacy_long_timeseries,
    long_timeseries,
    polars_converter,
)
from bookshelf._consume.memo import remember_resource, remembered_resource
from bookshelf._consume.presentation import Describable, Section, Sections
from bookshelf._consume.reading import (
    DataPreview,
    ResourceInfo,
    check_frame_read,
    check_preview,
    preview_params,
    resource_info,
    selection_rejections,
    settle_cached,
    settle_preview,
    settle_selected,
    unknown_platform_column,
)
from bookshelf._consume.selection import Filters, Order, Selection, unknown_filter_column
from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import BookshelfError, SelectionError
from bookshelf._core.frames import ParquetScan, read_frame, require_payload, to_pandas
from bookshelf._generated import models
from bookshelf._records import Facets, ResourceType, SeriesMetadata, Visibility
from bookshelf.cache import ContentCache, _staged

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa
    from scmdata import ScmRun

_FACET_MAX_VALUES = 500
_AS_DF_INT_YEARS = "as_df(int_years=True)"


class _ExternalPointer(Exception):
    """Aborts a cache fill because the resource points outside the platform's storage."""


def describe_type(resource_type: models.ResourceType | None) -> str:
    """Name a type the handle may not have learned yet."""
    return resource_type.value if resource_type is not None else "unknown"


def _resource_sections(
    resource_type: models.ResourceType | None,
    identity: dict[str, object],
) -> dict[str, Section]:
    """Build the sections every resource flavour renders."""
    return {"Identity": identity, "Read": readers_for(resource_type)}


def _entry_sections(
    entry: models.BookEntryItem,
    resource_type: models.ResourceType | None,
    book_id: UUID,
) -> dict[str, Section]:
    """Build the sections both entry flavours render."""
    identity: dict[str, object] = {
        "tracking_id": entry.tracking_id,
        "book_id": book_id,
        "visibility": entry.visibility.value,
    }
    return {**_resource_sections(resource_type, identity), "Explore": explorers_for(resource_type)}


def _entry_header(title: str, name_in_book: str, resource_type: models.ResourceType | None) -> str:
    """Name an entry and the type that decides which calls it answers."""
    return f"{title} {name_in_book!r} ({describe_type(resource_type)})"


def _copy_out(source: Path, destination: Path) -> Path:
    """Copy a cached file to a path the caller owns, so eviction cannot take it away."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _staged(destination) as staging:
        shutil.copyfile(source, staging)
    return destination


def _evicted(exc: BaseException) -> bool:
    """Whether a cached read failed because another process removed the file under it."""
    return isinstance(exc, FileNotFoundError) or isinstance(exc.__cause__, FileNotFoundError)


def _read_cached(
    resource_type: models.ResourceType, path: Path, selection: Selection
) -> pd.DataFrame:
    scans: list[ParquetScan] = []

    def scan(schema: pa.Schema) -> ParquetScan:
        scans.append(selection.parquet_scan(resource_type, schema))
        return scans[-1]

    frame = read_frame(path, scan=scan)
    coded = scans[0].dictionary if scans else None
    return settle_cached(resource_type, frame, selection, coded or ())


def _long(wide: pd.DataFrame, legacy_columns: bool, dropna: bool) -> pd.DataFrame:
    long = long_timeseries(wide, dropna=dropna)
    return legacy_long_timeseries(long) if legacy_columns else long


class _ResourceHandle(Describable):
    """Identity and lazily resolved metadata shared by both resource flavours."""

    _title = "Bookshelf Resource"

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
        """The platform's id for this resource."""
        self._metadata = metadata
        self._resource_type = resource_type
        self._content_hash: str | None = None if metadata is None else metadata.hash
        self._recalled = False

    def _recall(self) -> None:
        """Fill in the hash and type from the metadata cache, without a request."""
        if self._recalled:
            return
        remembered = remembered_resource(self._cache, self._client, self.tracking_id)
        if remembered is not None:
            self._content_hash, self._resource_type = remembered
        # Marked last, so a concurrent caller that sees the flag also sees the fields.
        self._recalled = True

    def _adopt(self, metadata: models.ResourceRead) -> models.ResourceRead:
        """Keep a freshly fetched record on the handle."""
        self._metadata = metadata
        self._resource_type = metadata.type
        self._content_hash = metadata.hash
        return metadata

    def _remember(self, metadata: models.ResourceRead) -> None:
        remember_resource(self._cache, self._client, metadata)

    def _summary(self) -> tuple[str, Sections]:
        # Only what the handle already knows, so printing it never reaches the platform.
        identity: dict[str, object] = {"tracking_id": self.tracking_id}
        if self._content_hash is not None:
            identity["hash"] = self._content_hash
        if self._metadata is not None:
            identity["visibility"] = self._metadata.visibility.value
        return (
            f"{self._title} ({describe_type(self._resource_type)})",
            _resource_sections(self._resource_type, identity),
        )


class Resource(_ResourceHandle):
    """Lean immutable resource handle for machine and provenance reads."""

    def _record(self) -> models.ResourceRead:
        if self._metadata is not None:
            return self._metadata
        metadata = self._adopt(self._client.get_resource(self.tracking_id))
        self._remember(metadata)
        return metadata

    def _kind(self) -> models.ResourceType:
        if self._resource_type is None:
            self._recall()
        if self._resource_type is None:
            return self._record().type
        return self._resource_type

    def resource_type(self) -> ResourceType:
        """Return the canonical resource type, from memory or disk before the platform."""
        return records.resource_type(self._kind())

    def describe(self) -> ResourceInfo:
        """Return what the platform records about the resource, fetching it at most once."""
        return resource_info(self._record())

    def content_hash(self) -> str:
        """Return the declared ``sha256:`` digest, from memory or disk before the platform."""
        if self._content_hash is None:
            self._recall()
        if self._content_hash is None:
            return self._record().hash
        return self._content_hash

    def _data(
        self, params: Mapping[str, str], *, limit: int | None = None, order: str | None = None
    ) -> pd.DataFrame:
        try:
            with selection_rejections():
                payload = self._client.query_resource_data(
                    self.tracking_id, limit=limit, order=order, filters=params
                )
        except SelectionError as exc:
            column = unknown_platform_column(exc)
            if column is None:
                raise
            try:
                first = self._client.query_resource_data(self.tracking_id, limit=1)
                sample = shape_frame(self._kind(), to_pandas(require_payload(first)))
            except BookshelfError:
                raise exc from None
            raise unknown_filter_column(column, sample) from exc
        return to_pandas(require_payload(payload))

    def _read(
        self,
        caller: str,
        filters: Filters | None,
        year_min: int | None,
        year_max: int | None,
        server_side: bool,
        order: Order | None = None,
        *,
        timeseries_only: bool = False,
    ) -> pd.DataFrame:
        selection = Selection.build(filters, year_min=year_min, year_max=year_max, order=order)
        resource_type = self._kind()
        check_frame_read(resource_type, selection, caller, timeseries_only=timeseries_only)
        if not server_side:
            try:
                return self._through_cache(
                    lambda path: _read_cached(resource_type, path, selection), managed_only=True
                )
            except _ExternalPointer:
                pass
        # An external pointer has no cached file, so the platform selects it where it lives.
        return settle_selected(resource_type, self._data(selection.data_params()), selection)

    def as_df(
        self,
        *,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        server_side: bool = False,
        order: Order | None = None,
        int_years: bool = False,
    ) -> pd.DataFrame:
        """Return every selected row as pandas, using wide indexed form for timeseries.

        Values listed for one filter are alternatives, and separate filters must all hold.
        The year window is inclusive.
        ``order`` names columns to sort by, each prefixed with ``-`` to sort descending,
        with missing values first either way and no promised order among ties.
        By default the selection applies to the verified cached file,
        and ``server_side`` has the platform select instead, which transfers only the selected rows.
        Both pick the same rows, but without ``order`` the platform returns them in its own order.
        ``int_years`` labels a timeseries' year columns as integers rather than strings.
        """
        frame = self._read(
            _AS_DF_INT_YEARS if int_years else "as_df()",
            filters,
            year_min,
            year_max,
            server_side,
            order,
            timeseries_only=int_years,
        )
        return int_year_columns(frame) if int_years else frame

    def as_long_df(
        self,
        *,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        server_side: bool = False,
        legacy_columns: bool = False,
        dropna: bool = False,
    ) -> pd.DataFrame:
        """Return tidy pandas timeseries data, with integer ``year`` and a ``value`` column.

        Every series has a row for every year, missing values included.
        ``dropna`` leaves out the rows with no value, without ever building them,
        which keeps a sparse resource far smaller in memory.
        ``legacy_columns`` reproduces the 0.4 long format instead:
        a ``values`` column, a ``year`` column of ``YYYY-01-01 00:00:00`` strings,
        and rows sorted by the dimensions and then the year.
        """
        wide = self._read(
            "as_long_df()", filters, year_min, year_max, server_side, timeseries_only=True
        )
        return _long(wide, legacy_columns, dropna)

    def as_polars(
        self,
        *,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        server_side: bool = False,
        order: Order | None = None,
    ) -> pl.DataFrame:
        """Return the selection as a Polars DataFrame, with the dimensions as columns."""
        convert = polars_converter()
        return convert(self._read("as_polars()", filters, year_min, year_max, server_side, order))

    def as_arrow(
        self,
        *,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        server_side: bool = False,
        order: Order | None = None,
    ) -> pa.Table:
        """Return the selection as a PyArrow table, with the dimensions as columns."""
        convert = arrow_converter()
        return convert(self._read("as_arrow()", filters, year_min, year_max, server_side, order))

    def as_scmrun(
        self,
        *,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        server_side: bool = False,
    ) -> ScmRun:
        """Return timeseries data as an scmdata ScmRun.

        scmdata rejects rows with duplicate metadata.
        """
        run = scmrun_class()
        return run(
            self._read(
                "as_scmrun()", filters, year_min, year_max, server_side, timeseries_only=True
            )
        )

    def preview(
        self,
        *,
        limit: int = 100,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        order: Order | None = None,
        top_n: int | None = None,
        drop_constant: bool = False,
    ) -> DataPreview:
        """Return up to ``limit`` selected rows, selected on the platform, and whether that is all.

        ``order`` names columns to sort by first, each prefixed with ``-`` to sort descending.
        ``top_n`` keeps the timeseries with the largest latest values, and cannot take an order.
        ``drop_constant`` drops the dimensions that hold one value across the returned series.
        """
        selection = Selection.build(filters, year_min=year_min, year_max=year_max, order=order)
        resource_type = self._kind()
        limit, top_n = check_preview(
            resource_type, selection, limit=limit, top_n=top_n, drop_constant=drop_constant
        )
        frame = self._data(
            preview_params(selection, top_n=top_n), limit=limit + 1, order=selection.order_param()
        )
        return settle_preview(resource_type, frame, limit=limit, drop_constant=drop_constant)

    def fetch(self) -> bytes:
        """Return verified bytes, using memory proportional to the resource size.

        Use `download()` to write large resources to disk without loading them into memory.
        """
        return self._through_cache(Path.read_bytes)

    def download(self, destination: str | Path) -> Path:
        """Stream and verify the resource, then copy it to ``destination`` and return that path."""
        destination = Path(destination)
        return self._through_cache(lambda path: _copy_out(path, destination))

    def as_path(self) -> Path:
        """Stream and verify the resource, then return its path in the cache.

        The cache may evict the file later, so use `download()` for a copy that stays.
        """
        return self._ensure_cached()

    def _through_cache[T](self, read: Callable[[Path], T], *, managed_only: bool = False) -> T:
        """Run ``read`` on the cached file, downloading it again once if the cache drops it."""
        try:
            return read(self._ensure_cached(managed_only=managed_only))
        except (FileNotFoundError, BookshelfError) as exc:
            if not _evicted(exc):
                raise
        return read(self._ensure_cached(managed_only=managed_only))

    def _ensure_cached(self, *, managed_only: bool = False) -> Path:
        def download(destination: Path) -> None:
            pointer = self._client.get_resource_download(self.tracking_id)
            # The platform names managed bytes only, so no filename means an external pointer.
            if managed_only and pointer.filename is None:
                raise _ExternalPointer
            self._client.stream_url_to_path(pointer.presigned_url, destination)

        return self._cache.fetch(self.content_hash(), download)


class BookEntry(Resource):
    """A resource handle with its book scoped exploration capabilities."""

    _title = "Bookshelf Book Entry"

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        book_id: str | UUID,
        entry: models.BookEntryItem,
    ) -> None:
        super().__init__(client, cache, entry.tracking_id, resource_type=entry.type)
        self.book_id = UUID(str(book_id))
        """The id of the book this entry belongs to."""
        self._entry = entry
        self.name_in_book = entry.name_in_book
        """The name this entry has in its book."""

    @property
    def visibility(self) -> Visibility:
        """Who can read this entry within its book."""
        return records.visibility(self._entry.visibility)

    def _summary(self) -> tuple[str, Sections]:
        return _entry_header(self._title, self.name_in_book, self._resource_type), _entry_sections(
            self._entry, self._resource_type, self.book_id
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
        self, *, max_values: int = _FACET_MAX_VALUES, filters: Filters | None = None
    ) -> Facets:
        """Return the distinct values of each column, within the book."""
        selection = Selection.build(filters, year_min=None, year_max=None)
        response = self._client.get_book_resource_facets(
            self.book_id,
            self.name_in_book,
            max_values=max_values,
            filters=selection.book_params(),
        )
        return records.facets(response)

    def series_metadata(self, *, limit: int = 100, offset: int = 0) -> SeriesMetadata:
        """Return a page of the timeseries' series, one record of dimension values per series."""
        response = self._client.get_book_resource_schema(
            self.book_id,
            self.name_in_book,
            limit=limit,
            offset=offset,
        )
        return records.series_metadata(response)


class AsyncResource(_ResourceHandle):
    """Asynchronous lean immutable resource handle."""

    _title = "Bookshelf Async Resource"

    async def _record(self) -> models.ResourceRead:
        if self._metadata is not None:
            return self._metadata
        metadata = self._adopt(await self._client.get_resource_async(self.tracking_id))
        await asyncio.to_thread(self._remember, metadata)
        return metadata

    async def _kind(self) -> models.ResourceType:
        if self._resource_type is None:
            await asyncio.to_thread(self._recall)
        if self._resource_type is None:
            return (await self._record()).type
        return self._resource_type

    async def resource_type(self) -> ResourceType:
        """Return the canonical resource type, from memory or disk before the platform."""
        return records.resource_type(await self._kind())

    async def describe(self) -> ResourceInfo:
        """Return what the platform records about the resource, fetching it at most once."""
        return resource_info(await self._record())

    async def content_hash(self) -> str:
        """Return the declared ``sha256:`` digest, from memory or disk before the platform."""
        if self._content_hash is None:
            await asyncio.to_thread(self._recall)
        if self._content_hash is None:
            return (await self._record()).hash
        return self._content_hash

    async def _data(
        self, params: Mapping[str, str], *, limit: int | None = None, order: str | None = None
    ) -> pd.DataFrame:
        try:
            with selection_rejections():
                payload = await self._client.query_resource_data_async(
                    self.tracking_id, limit=limit, order=order, filters=params
                )
        except SelectionError as exc:
            column = unknown_platform_column(exc)
            if column is None:
                raise
            try:
                first = await self._client.query_resource_data_async(self.tracking_id, limit=1)
                sample = shape_frame(await self._kind(), to_pandas(require_payload(first)))
            except BookshelfError:
                raise exc from None
            raise unknown_filter_column(column, sample) from exc
        return await asyncio.to_thread(to_pandas, require_payload(payload))

    async def _read(
        self,
        caller: str,
        filters: Filters | None,
        year_min: int | None,
        year_max: int | None,
        server_side: bool,
        order: Order | None = None,
        *,
        timeseries_only: bool = False,
    ) -> pd.DataFrame:
        selection = Selection.build(filters, year_min=year_min, year_max=year_max, order=order)
        resource_type = await self._kind()
        check_frame_read(resource_type, selection, caller, timeseries_only=timeseries_only)
        if not server_side:
            try:
                return await self._through_cache(
                    lambda path: _read_cached(resource_type, path, selection), managed_only=True
                )
            except _ExternalPointer:
                pass
        # An external pointer has no cached file, so the platform selects it where it lives.
        frame = await self._data(selection.data_params())
        return await asyncio.to_thread(settle_selected, resource_type, frame, selection)

    async def as_df(
        self,
        *,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        server_side: bool = False,
        order: Order | None = None,
        int_years: bool = False,
    ) -> pd.DataFrame:
        """Return every selected row as pandas, using wide indexed form for timeseries.

        Values listed for one filter are alternatives, and separate filters must all hold.
        The year window is inclusive.
        ``order`` names columns to sort by, each prefixed with ``-`` to sort descending,
        with missing values first either way and no promised order among ties.
        By default the selection applies to the verified cached file,
        and ``server_side`` has the platform select instead, which transfers only the selected rows.
        Both pick the same rows, but without ``order`` the platform returns them in its own order.
        ``int_years`` labels a timeseries' year columns as integers rather than strings.
        """
        frame = await self._read(
            _AS_DF_INT_YEARS if int_years else "as_df()",
            filters,
            year_min,
            year_max,
            server_side,
            order,
            timeseries_only=int_years,
        )
        return int_year_columns(frame) if int_years else frame

    async def as_long_df(
        self,
        *,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        server_side: bool = False,
        legacy_columns: bool = False,
        dropna: bool = False,
    ) -> pd.DataFrame:
        """Return tidy pandas timeseries data, with integer ``year`` and a ``value`` column.

        Every series has a row for every year, missing values included.
        ``dropna`` leaves out the rows with no value, without ever building them,
        which keeps a sparse resource far smaller in memory.
        ``legacy_columns`` reproduces the 0.4 long format instead:
        a ``values`` column, a ``year`` column of ``YYYY-01-01 00:00:00`` strings,
        and rows sorted by the dimensions and then the year.
        """
        wide = await self._read(
            "as_long_df()", filters, year_min, year_max, server_side, timeseries_only=True
        )
        return await asyncio.to_thread(_long, wide, legacy_columns, dropna)

    async def as_polars(
        self,
        *,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        server_side: bool = False,
        order: Order | None = None,
    ) -> pl.DataFrame:
        """Return the selection as a Polars DataFrame, with the dimensions as columns."""
        convert = polars_converter()
        frame = await self._read("as_polars()", filters, year_min, year_max, server_side, order)
        return await asyncio.to_thread(convert, frame)

    async def as_arrow(
        self,
        *,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        server_side: bool = False,
        order: Order | None = None,
    ) -> pa.Table:
        """Return the selection as a PyArrow table, with the dimensions as columns."""
        convert = arrow_converter()
        frame = await self._read("as_arrow()", filters, year_min, year_max, server_side, order)
        return await asyncio.to_thread(convert, frame)

    async def as_scmrun(
        self,
        *,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        server_side: bool = False,
    ) -> ScmRun:
        """Return timeseries data as an scmdata ScmRun.

        scmdata rejects rows with duplicate metadata.
        """
        run = scmrun_class()
        frame = await self._read(
            "as_scmrun()", filters, year_min, year_max, server_side, timeseries_only=True
        )
        return await asyncio.to_thread(run, frame)

    async def preview(
        self,
        *,
        limit: int = 100,
        filters: Filters | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        order: Order | None = None,
        top_n: int | None = None,
        drop_constant: bool = False,
    ) -> DataPreview:
        """Return up to ``limit`` selected rows, selected on the platform, and whether that is all.

        ``order`` names columns to sort by first, each prefixed with ``-`` to sort descending.
        ``top_n`` keeps the timeseries with the largest latest values, and cannot take an order.
        ``drop_constant`` drops the dimensions that hold one value across the returned series.
        """
        selection = Selection.build(filters, year_min=year_min, year_max=year_max, order=order)
        resource_type = await self._kind()
        limit, top_n = check_preview(
            resource_type, selection, limit=limit, top_n=top_n, drop_constant=drop_constant
        )
        frame = await self._data(
            preview_params(selection, top_n=top_n), limit=limit + 1, order=selection.order_param()
        )
        return await asyncio.to_thread(
            settle_preview, resource_type, frame, limit=limit, drop_constant=drop_constant
        )

    async def fetch(self) -> bytes:
        """Return verified bytes, using memory proportional to the resource size.

        Use `download()` to write large resources to disk without loading them into memory.
        """
        return await self._through_cache(Path.read_bytes)

    async def download(self, destination: str | Path) -> Path:
        """Stream and verify the resource, then copy it to ``destination`` and return that path."""
        destination = Path(destination)
        return await self._through_cache(lambda path: _copy_out(path, destination))

    async def as_path(self) -> Path:
        """Stream and verify the resource, then return its path in the cache.

        The cache may evict the file later, so use `download()` for a copy that stays.
        """
        return await self._ensure_cached()

    async def _through_cache[T](
        self, read: Callable[[Path], T], *, managed_only: bool = False
    ) -> T:
        """Run ``read`` on the cached file, downloading it again once if the cache drops it."""
        try:
            path = await self._ensure_cached(managed_only=managed_only)
            return await asyncio.to_thread(read, path)
        except (FileNotFoundError, BookshelfError) as exc:
            if not _evicted(exc):
                raise
        path = await self._ensure_cached(managed_only=managed_only)
        return await asyncio.to_thread(read, path)

    async def _ensure_cached(self, *, managed_only: bool = False) -> Path:
        async def download(destination: Path) -> None:
            pointer = await self._client.get_resource_download_async(self.tracking_id)
            # The platform names managed bytes only, so no filename means an external pointer.
            if managed_only and pointer.filename is None:
                raise _ExternalPointer
            await self._client.stream_url_to_path_async(pointer.presigned_url, destination)

        return await self._cache.fetch_async(await self.content_hash(), download)


class AsyncBookEntry(AsyncResource):
    """An async resource handle with book scoped exploration capabilities."""

    _title = "Bookshelf Async Book Entry"

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        book_id: str | UUID,
        entry: models.BookEntryItem,
    ) -> None:
        super().__init__(client, cache, entry.tracking_id, resource_type=entry.type)
        self.book_id = UUID(str(book_id))
        """The id of the book this entry belongs to."""
        self._entry = entry
        self.name_in_book = entry.name_in_book
        """The name this entry has in its book."""

    @property
    def visibility(self) -> Visibility:
        """Who can read this entry within its book."""
        return records.visibility(self._entry.visibility)

    def _summary(self) -> tuple[str, Sections]:
        return _entry_header(self._title, self.name_in_book, self._resource_type), _entry_sections(
            self._entry, self._resource_type, self.book_id
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
        self, *, max_values: int = _FACET_MAX_VALUES, filters: Filters | None = None
    ) -> Facets:
        """Return the distinct values of each column, within the book."""
        selection = Selection.build(filters, year_min=None, year_max=None)
        response = await self._client.get_book_resource_facets_async(
            self.book_id,
            self.name_in_book,
            max_values=max_values,
            filters=selection.book_params(),
        )
        return records.facets(response)

    async def series_metadata(self, *, limit: int = 100, offset: int = 0) -> SeriesMetadata:
        """Return a page of the timeseries' series, one record of dimension values per series."""
        response = await self._client.get_book_resource_schema_async(
            self.book_id,
            self.name_in_book,
            limit=limit,
            offset=offset,
        )
        return records.series_metadata(response)


__all__ = ["AsyncBookEntry", "AsyncResource", "BookEntry", "Resource", "describe_type"]
