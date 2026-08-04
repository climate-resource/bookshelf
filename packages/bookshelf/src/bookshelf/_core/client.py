"""Unified client for the Bookshelf SDK.

Every method is a logic-free shell over the I/O-free ``build_*``/``parse_*`` pair for its operation, so the two surfaces cannot drift.
Each surface owns a real httpx transport, created lazily on first use, and the client is long-lived by design.
The client is designed to be reused across multiple operations, so the transport is not closed after each request.
"""

import asyncio
import threading
import time
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Self
from uuid import UUID

import httpx

if TYPE_CHECKING:
    import pandas as pd

from bookshelf._core import ops
from bookshelf._core.config import UNSET, AuthInput, resolve_auth, resolve_base_url
from bookshelf._core.errors import TransportError
from bookshelf._core.frames import require_payload, to_pandas
from bookshelf._core.retry import RetryPolicy
from bookshelf._core.types import (
    ApiRequest,
    ApiResponse,
    DataFormat,
    DataPayload,
    NotModified,
)
from bookshelf._generated import models

_USER_AGENT = "bookshelf-python"


class BookshelfClient:
    """Long-lived unified client over both httpx surfaces.

    ``auth`` accepts any :class:`httpx.Auth` (including the credential providers),
    a bare token string, or ``None`` for explicit unauthenticated access.
    When omitted, ambient credentials are resolved
    (``$BOOKSHELF_TOKEN``, then client-credential env vars, then stored login).
    ``base_url`` falls back to ``$BOOKSHELF_URL`` (or its alias ``$BOOKSHELF_API_URL``)
    and then the production URL.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        auth: AuthInput = UNSET,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        transport: httpx.BaseTransport | None = None,
        async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = resolve_base_url(base_url).rstrip("/")
        self._auth = resolve_auth(auth, base_url=self._base_url)
        self._timeout = timeout
        self._retry = retry if retry is not None else RetryPolicy()
        self._transport = transport
        self._async_transport = async_transport
        self._sync: httpx.Client | None = None
        self._async: httpx.AsyncClient | None = None
        # One lock guards both lazy transports.
        # AsyncClient construction is synchronous code.
        # The async surface can therefore share it.
        self._init_lock = threading.Lock()

    @property
    def _sync_client(self) -> httpx.Client:
        if self._sync is None:
            with self._init_lock:
                if self._sync is None:
                    self._sync = httpx.Client(
                        base_url=self._base_url,
                        auth=self._auth,
                        timeout=self._timeout,
                        headers={"user-agent": _USER_AGENT},
                        transport=self._transport,
                    )
        return self._sync

    @property
    def _async_client(self) -> httpx.AsyncClient:
        if self._async is None:
            with self._init_lock:
                if self._async is None:
                    self._async = httpx.AsyncClient(
                        base_url=self._base_url,
                        auth=self._auth,
                        timeout=self._timeout,
                        headers={"user-agent": _USER_AGENT},
                        transport=self._async_transport,
                    )
        return self._async

    def close(self) -> None:
        if self._sync is not None:
            self._sync.close()
            self._sync = None
        if self._async is not None:
            warnings.warn(
                "close() does not close the async transport. "
                "Call aclose() when any _async method was used.",
                stacklevel=2,
            )

    async def aclose(self) -> None:
        if self._async is not None:
            await self._async.aclose()
            self._async = None
        self.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _httpx_request(
        self, client: httpx.Client | httpx.AsyncClient, req: ApiRequest
    ) -> httpx.Request:
        return client.build_request(
            req.method,
            req.absolute_url if req.absolute_url is not None else req.path,
            params=req.params or None,
            headers=req.headers or None,
            json=req.json_body,
            data=req.form_body,
            content=req.content,
        )

    @staticmethod
    def _api_response(response: httpx.Response) -> ApiResponse:
        return ApiResponse(
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            content=response.content,
        )

    def _send(self, req: ApiRequest) -> ApiResponse:
        client = self._sync_client
        attempt = 0
        while True:
            attempt += 1
            try:
                # A presigned PUT targets object storage: never forward the API credential.
                response = client.send(
                    self._httpx_request(client, req),
                    auth=None if req.absolute_url is not None else httpx.USE_CLIENT_DEFAULT,
                )
            except httpx.TransportError as exc:
                if attempt >= self._retry.max_attempts:
                    raise TransportError(str(exc)) from exc
            else:
                if (
                    not self._retry.should_retry_status(response.status_code)
                    or attempt >= self._retry.max_attempts
                ):
                    return self._api_response(response)
            time.sleep(self._retry.delay(attempt))

    async def _send_async(self, req: ApiRequest) -> ApiResponse:
        client = self._async_client
        attempt = 0
        while True:
            attempt += 1
            try:
                # A presigned PUT targets object storage: never forward the API credential.
                response = await client.send(
                    self._httpx_request(client, req),
                    auth=None if req.absolute_url is not None else httpx.USE_CLIENT_DEFAULT,
                )
            except httpx.TransportError as exc:
                if attempt >= self._retry.max_attempts:
                    raise TransportError(str(exc)) from exc
            else:
                if (
                    not self._retry.should_retry_status(response.status_code)
                    or attempt >= self._retry.max_attempts
                ):
                    return self._api_response(response)
            await asyncio.sleep(self._retry.delay(attempt))

    def register_resources(
        self, request: models.RegisterResourcesRequest
    ) -> models.RegisterResourcesResponse:
        return ops.parse_register_resources(self._send(ops.build_register_resources(request)))

    async def register_resources_async(
        self, request: models.RegisterResourcesRequest
    ) -> models.RegisterResourcesResponse:
        return ops.parse_register_resources(
            await self._send_async(ops.build_register_resources(request))
        )

    def put_presigned(
        self, url: str, content: bytes, *, content_type: str | None = None
    ) -> str | None:
        return ops.parse_put_presigned(
            self._send(ops.build_put_presigned(url, content, content_type=content_type))
        )

    async def put_presigned_async(
        self, url: str, content: bytes, *, content_type: str | None = None
    ) -> str | None:
        return ops.parse_put_presigned(
            await self._send_async(ops.build_put_presigned(url, content, content_type=content_type))
        )

    def query_resource_data(
        self,
        tracking_id: str | UUID,
        *,
        format: DataFormat = "parquet",
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        filters: Mapping[str, str] | None = None,
        if_none_match: str | None = None,
    ) -> DataPayload | NotModified:
        return ops.parse_query_resource_data(
            self._send(
                ops.build_query_resource_data(
                    tracking_id,
                    format=format,
                    select=select,
                    order=order,
                    limit=limit,
                    offset=offset,
                    filters=filters,
                    if_none_match=if_none_match,
                )
            )
        )

    async def query_resource_data_async(
        self,
        tracking_id: str | UUID,
        *,
        format: DataFormat = "parquet",
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        filters: Mapping[str, str] | None = None,
        if_none_match: str | None = None,
    ) -> DataPayload | NotModified:
        return ops.parse_query_resource_data(
            await self._send_async(
                ops.build_query_resource_data(
                    tracking_id,
                    format=format,
                    select=select,
                    order=order,
                    limit=limit,
                    offset=offset,
                    filters=filters,
                    if_none_match=if_none_match,
                )
            )
        )

    def query_resource_dataframe(
        self,
        tracking_id: str | UUID,
        *,
        format: DataFormat = "parquet",
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        filters: Mapping[str, str] | None = None,
    ) -> "pd.DataFrame":
        payload = self.query_resource_data(
            tracking_id,
            format=format,
            select=select,
            order=order,
            limit=limit,
            offset=offset,
            filters=filters,
        )
        return to_pandas(require_payload(payload))

    async def query_resource_dataframe_async(
        self,
        tracking_id: str | UUID,
        *,
        format: DataFormat = "parquet",
        select: str | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        filters: Mapping[str, str] | None = None,
    ) -> "pd.DataFrame":
        payload = await self.query_resource_data_async(
            tracking_id,
            format=format,
            select=select,
            order=order,
            limit=limit,
            offset=offset,
            filters=filters,
        )
        return to_pandas(require_payload(payload))

    def stream_url_to_path(self, url: str, destination: Path) -> None:
        """Stream an API issued content URL to a local path without API credentials."""
        with self._sync_client.stream("GET", url, auth=None) as response:
            if response.status_code // 100 != 2:
                response.read()
                ops.parse_get_url(self._api_response(response))
            with destination.open("wb") as stream:
                for chunk in response.iter_bytes():
                    stream.write(chunk)

    async def stream_url_to_path_async(self, url: str, destination: Path) -> None:
        """Stream an API issued content URL to a local path without API credentials."""
        async with self._async_client.stream("GET", url, auth=None) as response:
            if response.status_code // 100 != 2:
                await response.aread()
                ops.parse_get_url(self._api_response(response))
            with destination.open("wb") as stream:
                async for chunk in response.aiter_bytes():
                    stream.write(chunk)

    def publish_book(self, book_id: str) -> models.BookDetail:
        return ops.parse_publish_book(self._send(ops.build_publish_book(book_id)))

    async def publish_book_async(self, book_id: str) -> models.BookDetail:
        return ops.parse_publish_book(await self._send_async(ops.build_publish_book(book_id)))

    def update_book(self, book_id: str, request: models.BookUpdate) -> models.BookResponse:
        return ops.parse_update_book(self._send(ops.build_update_book(book_id, request)))

    async def update_book_async(
        self, book_id: str, request: models.BookUpdate
    ) -> models.BookResponse:
        return ops.parse_update_book(
            await self._send_async(ops.build_update_book(book_id, request))
        )

    def list_resources(
        self,
        *,
        logical_key: str | None = None,
        type: str | None = None,
        tags: Sequence[str] | None = None,
        owner_org_id: str | None = None,
        latest: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> models.ResourceListResponse:
        return ops.parse_list_resources(
            self._send(
                ops.build_list_resources(
                    logical_key=logical_key,
                    type=type,
                    tags=tags,
                    owner_org_id=owner_org_id,
                    latest=latest,
                    limit=limit,
                    cursor=cursor,
                )
            )
        )

    async def list_resources_async(
        self,
        *,
        logical_key: str | None = None,
        type: str | None = None,
        tags: Sequence[str] | None = None,
        owner_org_id: str | None = None,
        latest: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> models.ResourceListResponse:
        return ops.parse_list_resources(
            await self._send_async(
                ops.build_list_resources(
                    logical_key=logical_key,
                    type=type,
                    tags=tags,
                    owner_org_id=owner_org_id,
                    latest=latest,
                    limit=limit,
                    cursor=cursor,
                )
            )
        )

    def list_resource_events(
        self,
        tracking_id: str | UUID,
        *,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> models.RegistrationEventsResponse:
        return ops.parse_list_resource_events(
            self._send(
                ops.build_list_resource_events(
                    tracking_id, since=since, until=until, limit=limit, cursor=cursor
                )
            )
        )

    async def list_resource_events_async(
        self,
        tracking_id: str | UUID,
        *,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> models.RegistrationEventsResponse:
        return ops.parse_list_resource_events(
            await self._send_async(
                ops.build_list_resource_events(
                    tracking_id, since=since, until=until, limit=limit, cursor=cursor
                )
            )
        )

    def list_volumes(
        self,
        *,
        q: str | None = None,
        topic: Sequence[str] | None = None,
        keyword: Sequence[str] | None = None,
        region: Sequence[str] | None = None,
        publisher: str | None = None,
        license: str | None = None,
        coverage_year: int | None = None,
        resource_type: str | None = None,
        deprecated: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> models.VolumeListResponse:
        return ops.parse_list_volumes(
            self._send(
                ops.build_list_volumes(
                    q=q,
                    topic=topic,
                    keyword=keyword,
                    region=region,
                    publisher=publisher,
                    license=license,
                    coverage_year=coverage_year,
                    resource_type=resource_type,
                    deprecated=deprecated,
                    limit=limit,
                    offset=offset,
                )
            )
        )

    async def list_volumes_async(
        self,
        *,
        q: str | None = None,
        topic: Sequence[str] | None = None,
        keyword: Sequence[str] | None = None,
        region: Sequence[str] | None = None,
        publisher: str | None = None,
        license: str | None = None,
        coverage_year: int | None = None,
        resource_type: str | None = None,
        deprecated: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> models.VolumeListResponse:
        return ops.parse_list_volumes(
            await self._send_async(
                ops.build_list_volumes(
                    q=q,
                    topic=topic,
                    keyword=keyword,
                    region=region,
                    publisher=publisher,
                    license=license,
                    coverage_year=coverage_year,
                    resource_type=resource_type,
                    deprecated=deprecated,
                    limit=limit,
                    offset=offset,
                )
            )
        )

    def update_volume(
        self, volume_name: str, request: models.VolumeUpdate
    ) -> models.VolumeResponse:
        return ops.parse_update_volume(self._send(ops.build_update_volume(volume_name, request)))

    async def update_volume_async(
        self, volume_name: str, request: models.VolumeUpdate
    ) -> models.VolumeResponse:
        return ops.parse_update_volume(
            await self._send_async(ops.build_update_volume(volume_name, request))
        )

    def register_agent_identity(
        self, request: models.AgentIdentityRequest
    ) -> models.AnonymousRegistrationResponse | models.ServiceAuthRegistrationResponse:
        return ops.parse_register_agent_identity(
            self._send(ops.build_register_agent_identity(request))
        )

    async def register_agent_identity_async(
        self, request: models.AgentIdentityRequest
    ) -> models.AnonymousRegistrationResponse | models.ServiceAuthRegistrationResponse:
        return ops.parse_register_agent_identity(
            await self._send_async(ops.build_register_agent_identity(request))
        )

    # --- BEGIN GENERATED OPERATIONS ---
    # Generated by packages/bookshelf/scripts/generate_client.py
    # from the build_*/parse_* pairs in bookshelf/_core/ops.py.
    # Everything below this line is overwritten on every run, so never edit it by hand.
    # To add an operation, add its build_*/parse_* pair to ops.py and regenerate.

    def agent_token_exchange(self, request: models.BodyAgentTokenExchange) -> models.TokenResponse:
        return ops.parse_agent_token_exchange(self._send(ops.build_agent_token_exchange(request)))

    async def agent_token_exchange_async(
        self, request: models.BodyAgentTokenExchange
    ) -> models.TokenResponse:
        return ops.parse_agent_token_exchange(
            await self._send_async(ops.build_agent_token_exchange(request))
        )

    def agent_token_revoke(self, request: models.BodyAgentTokenRevoke) -> None:
        ops.parse_agent_token_revoke(self._send(ops.build_agent_token_revoke(request)))

    async def agent_token_revoke_async(self, request: models.BodyAgentTokenRevoke) -> None:
        ops.parse_agent_token_revoke(await self._send_async(ops.build_agent_token_revoke(request)))

    def attach_entry(
        self, book_id: str, request: models.BookEntryAttach
    ) -> models.BookEntryAttachResponse:
        return ops.parse_attach_entry(self._send(ops.build_attach_entry(book_id, request)))

    async def attach_entry_async(
        self, book_id: str, request: models.BookEntryAttach
    ) -> models.BookEntryAttachResponse:
        return ops.parse_attach_entry(
            await self._send_async(ops.build_attach_entry(book_id, request))
        )

    def complete_ingest_upload(self, request: models.IngestUploadCompleteRequest) -> None:
        ops.parse_complete_ingest_upload(self._send(ops.build_complete_ingest_upload(request)))

    async def complete_ingest_upload_async(
        self, request: models.IngestUploadCompleteRequest
    ) -> None:
        ops.parse_complete_ingest_upload(
            await self._send_async(ops.build_complete_ingest_upload(request))
        )

    def create_volume(self, request: models.VolumeCreate) -> models.VolumeResponse:
        return ops.parse_create_volume(self._send(ops.build_create_volume(request)))

    async def create_volume_async(self, request: models.VolumeCreate) -> models.VolumeResponse:
        return ops.parse_create_volume(await self._send_async(ops.build_create_volume(request)))

    def delete_book(self, book_id: str) -> None:
        ops.parse_delete_book(self._send(ops.build_delete_book(book_id)))

    async def delete_book_async(self, book_id: str) -> None:
        ops.parse_delete_book(await self._send_async(ops.build_delete_book(book_id)))

    def delete_volume(self, volume_name: str) -> None:
        ops.parse_delete_volume(self._send(ops.build_delete_volume(volume_name)))

    async def delete_volume_async(self, volume_name: str) -> None:
        ops.parse_delete_volume(await self._send_async(ops.build_delete_volume(volume_name)))

    def draft_book(self, request: models.BookDraftRequest) -> models.BookDetail:
        return ops.parse_draft_book(self._send(ops.build_draft_book(request)))

    async def draft_book_async(self, request: models.BookDraftRequest) -> models.BookDetail:
        return ops.parse_draft_book(await self._send_async(ops.build_draft_book(request)))

    def get_book(self, book_id: str) -> models.BookResponse:
        return ops.parse_get_book(self._send(ops.build_get_book(book_id)))

    async def get_book_async(self, book_id: str) -> models.BookResponse:
        return ops.parse_get_book(await self._send_async(ops.build_get_book(book_id)))

    def get_book_resource_facets(
        self,
        book_id: str | UUID,
        resource_name: str,
        *,
        max_values: int | None = None,
        filters: Mapping[str, str] | None = None,
    ) -> models.FacetsResponse:
        return ops.parse_get_book_resource_facets(
            self._send(
                ops.build_get_book_resource_facets(
                    book_id, resource_name, max_values=max_values, filters=filters
                )
            )
        )

    async def get_book_resource_facets_async(
        self,
        book_id: str | UUID,
        resource_name: str,
        *,
        max_values: int | None = None,
        filters: Mapping[str, str] | None = None,
    ) -> models.FacetsResponse:
        return ops.parse_get_book_resource_facets(
            await self._send_async(
                ops.build_get_book_resource_facets(
                    book_id, resource_name, max_values=max_values, filters=filters
                )
            )
        )

    def get_book_resource_preview(
        self,
        book_id: str | UUID,
        resource_name: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> models.PreviewResponse:
        return ops.parse_get_book_resource_preview(
            self._send(
                ops.build_get_book_resource_preview(
                    book_id, resource_name, limit=limit, offset=offset
                )
            )
        )

    async def get_book_resource_preview_async(
        self,
        book_id: str | UUID,
        resource_name: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> models.PreviewResponse:
        return ops.parse_get_book_resource_preview(
            await self._send_async(
                ops.build_get_book_resource_preview(
                    book_id, resource_name, limit=limit, offset=offset
                )
            )
        )

    def get_book_resource_schema(
        self,
        book_id: str | UUID,
        resource_name: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> models.TimeseriesMetadataResponse:
        return ops.parse_get_book_resource_schema(
            self._send(
                ops.build_get_book_resource_schema(
                    book_id, resource_name, limit=limit, offset=offset
                )
            )
        )

    async def get_book_resource_schema_async(
        self,
        book_id: str | UUID,
        resource_name: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> models.TimeseriesMetadataResponse:
        return ops.parse_get_book_resource_schema(
            await self._send_async(
                ops.build_get_book_resource_schema(
                    book_id, resource_name, limit=limit, offset=offset
                )
            )
        )

    def get_book_resource_timeseries(
        self,
        book_id: str | UUID,
        resource_name: str,
        *,
        drop: Sequence[str] | None = None,
        limit: int | None = None,
        top_n: int | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        filters: Mapping[str, str | list[str]] | None = None,
    ) -> models.TimeseriesResponse:
        return ops.parse_get_book_resource_timeseries(
            self._send(
                ops.build_get_book_resource_timeseries(
                    book_id,
                    resource_name,
                    drop=drop,
                    limit=limit,
                    top_n=top_n,
                    year_min=year_min,
                    year_max=year_max,
                    filters=filters,
                )
            )
        )

    async def get_book_resource_timeseries_async(
        self,
        book_id: str | UUID,
        resource_name: str,
        *,
        drop: Sequence[str] | None = None,
        limit: int | None = None,
        top_n: int | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        filters: Mapping[str, str | list[str]] | None = None,
    ) -> models.TimeseriesResponse:
        return ops.parse_get_book_resource_timeseries(
            await self._send_async(
                ops.build_get_book_resource_timeseries(
                    book_id,
                    resource_name,
                    drop=drop,
                    limit=limit,
                    top_n=top_n,
                    year_min=year_min,
                    year_max=year_max,
                    filters=filters,
                )
            )
        )

    def get_catalogue_facets(self) -> models.VolumeFacets:
        return ops.parse_get_catalogue_facets(self._send(ops.build_get_catalogue_facets()))

    async def get_catalogue_facets_async(self) -> models.VolumeFacets:
        return ops.parse_get_catalogue_facets(
            await self._send_async(ops.build_get_catalogue_facets())
        )

    def get_current_user(self) -> models.UserResponse:
        return ops.parse_get_current_user(self._send(ops.build_get_current_user()))

    async def get_current_user_async(self) -> models.UserResponse:
        return ops.parse_get_current_user(await self._send_async(ops.build_get_current_user()))

    def get_resource(
        self, tracking_id: str | UUID, *, as_of: str | None = None
    ) -> models.ResourceRead:
        return ops.parse_get_resource(self._send(ops.build_get_resource(tracking_id, as_of=as_of)))

    async def get_resource_async(
        self, tracking_id: str | UUID, *, as_of: str | None = None
    ) -> models.ResourceRead:
        return ops.parse_get_resource(
            await self._send_async(ops.build_get_resource(tracking_id, as_of=as_of))
        )

    def get_resource_download(
        self, tracking_id: str | UUID, *, expires_in: int | None = None
    ) -> models.DownloadResponse:
        return ops.parse_get_resource_download(
            self._send(ops.build_get_resource_download(tracking_id, expires_in=expires_in))
        )

    async def get_resource_download_async(
        self, tracking_id: str | UUID, *, expires_in: int | None = None
    ) -> models.DownloadResponse:
        return ops.parse_get_resource_download(
            await self._send_async(
                ops.build_get_resource_download(tracking_id, expires_in=expires_in)
            )
        )

    def get_url(self, url: str) -> bytes:
        return ops.parse_get_url(self._send(ops.build_get_url(url)))

    async def get_url_async(self, url: str) -> bytes:
        return ops.parse_get_url(await self._send_async(ops.build_get_url(url)))

    def get_volume(self, volume_name: str) -> models.VolumeDetailResponse:
        return ops.parse_get_volume(self._send(ops.build_get_volume(volume_name)))

    async def get_volume_async(self, volume_name: str) -> models.VolumeDetailResponse:
        return ops.parse_get_volume(await self._send_async(ops.build_get_volume(volume_name)))

    def initiate_ingest_upload(
        self, request: models.IngestUploadInitiateRequest
    ) -> models.UploadInitiateResponse | models.UploadAlreadyExistsResponse:
        return ops.parse_initiate_ingest_upload(
            self._send(ops.build_initiate_ingest_upload(request))
        )

    async def initiate_ingest_upload_async(
        self, request: models.IngestUploadInitiateRequest
    ) -> models.UploadInitiateResponse | models.UploadAlreadyExistsResponse:
        return ops.parse_initiate_ingest_upload(
            await self._send_async(ops.build_initiate_ingest_upload(request))
        )

    def invalidate_resource(
        self, tracking_id: str | UUID, request: models.InvalidateRequest
    ) -> models.InvalidateResponse:
        return ops.parse_invalidate_resource(
            self._send(ops.build_invalidate_resource(tracking_id, request))
        )

    async def invalidate_resource_async(
        self, tracking_id: str | UUID, request: models.InvalidateRequest
    ) -> models.InvalidateResponse:
        return ops.parse_invalidate_resource(
            await self._send_async(ops.build_invalidate_resource(tracking_id, request))
        )

    def list_book_entries(
        self, book_id: str, *, limit: int | None = None, cursor: str | None = None
    ) -> models.BookEntriesResponse:
        return ops.parse_list_book_entries(
            self._send(ops.build_list_book_entries(book_id, limit=limit, cursor=cursor))
        )

    async def list_book_entries_async(
        self, book_id: str, *, limit: int | None = None, cursor: str | None = None
    ) -> models.BookEntriesResponse:
        return ops.parse_list_book_entries(
            await self._send_async(ops.build_list_book_entries(book_id, limit=limit, cursor=cursor))
        )

    def list_books(
        self,
        *,
        volume: str | None = None,
        version: str | None = None,
        status: str | None = None,
        latest_only: bool | None = None,
        producer_version: str | None = None,
        config_hash: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> models.BookListResponse:
        return ops.parse_list_books(
            self._send(
                ops.build_list_books(
                    volume=volume,
                    version=version,
                    status=status,
                    latest_only=latest_only,
                    producer_version=producer_version,
                    config_hash=config_hash,
                    limit=limit,
                    offset=offset,
                )
            )
        )

    async def list_books_async(
        self,
        *,
        volume: str | None = None,
        version: str | None = None,
        status: str | None = None,
        latest_only: bool | None = None,
        producer_version: str | None = None,
        config_hash: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> models.BookListResponse:
        return ops.parse_list_books(
            await self._send_async(
                ops.build_list_books(
                    volume=volume,
                    version=version,
                    status=status,
                    latest_only=latest_only,
                    producer_version=producer_version,
                    config_hash=config_hash,
                    limit=limit,
                    offset=offset,
                )
            )
        )
