"""I/O-free ``build_*``/``parse_*`` pairs for every operation the SDK uses.

This module is the only hand-maintained request/response logic.
Both client shells route every call through the pair for its op,
so the sync and async surfaces cannot drift.

``OP_REGISTRY`` enumerates the covered operations.
The contract oracle walks it against the vendored OpenAPI spec.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel

from bookshelf._core import errors
from bookshelf._core.types import (
    ACCEPT_BY_FORMAT,
    FORMAT_BY_MEDIA_TYPE,
    ApiRequest,
    ApiResponse,
    DataFormat,
    DataPayload,
    NotModified,
)
from bookshelf._generated import models


@dataclass(frozen=True, slots=True)
class OpSpec:
    """A registry entry describing one covered API operation."""

    operation_id: str
    method: str
    path_template: str
    success_statuses: tuple[int, ...]
    error_statuses: tuple[int, ...]
    supplied_parameters: tuple[tuple[str, str], ...] = ()
    request_model: type[BaseModel] | None = None
    response_models: tuple[type[BaseModel], ...] = ()


OP_REGISTRY: dict[str, OpSpec] = {}


def _op(spec: OpSpec) -> OpSpec:
    OP_REGISTRY[spec.operation_id] = spec
    return spec


REGISTER_RESOURCES = _op(
    OpSpec(
        operation_id="registrationsRegisterResources",
        method="POST",
        path_template="/v1/resources/registrations",
        success_statuses=(200,),
        error_statuses=(400, 401, 403, 404, 409, 422),
        request_model=models.RegisterResourcesRequest,
        response_models=(models.RegisterResourcesResponse,),
    )
)
INITIATE_INGEST_UPLOAD = _op(
    OpSpec(
        operation_id="uploadsInitiateIngestUpload",
        method="POST",
        path_template="/v1/resources/uploads",
        success_statuses=(200,),
        error_statuses=(401, 403, 422),
        request_model=models.IngestUploadInitiateRequest,
        response_models=(models.UploadInitiateResponse, models.UploadAlreadyExistsResponse),
    )
)
COMPLETE_INGEST_UPLOAD = _op(
    OpSpec(
        operation_id="uploadsCompleteIngestUpload",
        method="POST",
        path_template="/v1/resources/uploads/complete",
        success_statuses=(204,),
        error_statuses=(401, 403, 422),
        request_model=models.IngestUploadCompleteRequest,
    )
)
QUERY_RESOURCE_DATA = _op(
    OpSpec(
        operation_id="dataQueryResourceData",
        method="GET",
        path_template="/v1/resources/{tracking_id}/data",
        success_statuses=(200, 304),
        error_statuses=(401, 403, 404, 422),
        supplied_parameters=(
            ("path", "tracking_id"),
            ("query", "select"),
            ("query", "order"),
            ("query", "limit"),
            ("query", "offset"),
            ("header", "If-None-Match"),
        ),
    )
)
GET_BOOK_RESOURCE_TIMESERIES = _op(
    OpSpec(
        operation_id="resourcesGetResourceTimeseries",
        method="GET",
        path_template="/v1/books/{book_id}/resources/{resource_name}/timeseries",
        success_statuses=(200,),
        error_statuses=(401, 403, 404, 422),
        supplied_parameters=(("path", "book_id"), ("path", "resource_name")),
    )
)
GET_BOOK_RESOURCE_FACETS = _op(
    OpSpec(
        operation_id="resourcesGetResourceFacets",
        method="GET",
        path_template="/v1/books/{book_id}/resources/{resource_name}/facets",
        success_statuses=(200,),
        error_statuses=(401, 403, 404, 422),
        supplied_parameters=(("path", "book_id"), ("path", "resource_name")),
    )
)
GET_BOOK_RESOURCE_PREVIEW = _op(
    OpSpec(
        operation_id="resourcesGetResourcePreview",
        method="GET",
        path_template="/v1/books/{book_id}/resources/{resource_name}/preview",
        success_statuses=(200,),
        error_statuses=(401, 403, 404, 422),
        supplied_parameters=(("path", "book_id"), ("path", "resource_name")),
    )
)
GET_BOOK_RESOURCE_SCHEMA = _op(
    OpSpec(
        operation_id="resourcesGetTimeseriesMetadata",
        method="GET",
        path_template="/v1/books/{book_id}/resources/{resource_name}/timeseries/metadata",
        success_statuses=(200,),
        error_statuses=(401, 403, 404, 422),
        supplied_parameters=(("path", "book_id"), ("path", "resource_name")),
    )
)
DRAFT_BOOK = _op(
    OpSpec(
        operation_id="bookActionsDraftBook",
        method="POST",
        path_template="/v1/books",
        success_statuses=(201,),
        error_statuses=(401, 403, 404, 409, 422),
        request_model=models.BookDraftRequest,
        response_models=(models.BookDetail,),
    )
)
ATTACH_ENTRY = _op(
    OpSpec(
        operation_id="bookActionsAttachEntry",
        method="POST",
        path_template="/v1/books/{book_id}/entries",
        success_statuses=(201,),
        error_statuses=(401, 403, 404, 409, 422),
        supplied_parameters=(("path", "book_id"),),
        request_model=models.BookEntryAttach,
        response_models=(models.BookEntryAttachResponse,),
    )
)
PUBLISH_BOOK = _op(
    OpSpec(
        operation_id="bookActionsPublishBook",
        method="POST",
        path_template="/v1/books/{book_id}/publish",
        success_statuses=(200,),
        error_statuses=(401, 403, 404, 409, 422),
        supplied_parameters=(("path", "book_id"),),
        response_models=(models.BookDetail,),
    )
)
LIST_BOOKS = _op(
    OpSpec(
        operation_id="booksListBooks",
        method="GET",
        path_template="/v1/books",
        success_statuses=(200,),
        error_statuses=(401, 404, 422),
        supplied_parameters=(
            ("query", "volume"),
            ("query", "version"),
            ("query", "status"),
            ("query", "latest_only"),
            ("query", "producer_version"),
            ("query", "config_hash"),
            ("query", "limit"),
            ("query", "offset"),
        ),
        response_models=(models.BookListResponse,),
    )
)
GET_BOOK = _op(
    OpSpec(
        operation_id="booksGetBook",
        method="GET",
        path_template="/v1/books/{book_id}",
        success_statuses=(200,),
        error_statuses=(401, 404, 422),
        supplied_parameters=(("path", "book_id"),),
        response_models=(models.BookResponse,),
    )
)
UPDATE_BOOK = _op(
    OpSpec(
        operation_id="booksUpdateBook",
        method="PATCH",
        path_template="/v1/books/{book_id}",
        success_statuses=(200,),
        error_statuses=(400, 401, 403, 404, 422),
        supplied_parameters=(("path", "book_id"),),
        request_model=models.BookUpdate,
        response_models=(models.BookResponse,),
    )
)
DELETE_BOOK = _op(
    OpSpec(
        operation_id="booksDeleteBook",
        method="DELETE",
        path_template="/v1/books/{book_id}",
        success_statuses=(204,),
        error_statuses=(400, 401, 403, 404, 422),
        supplied_parameters=(("path", "book_id"),),
    )
)
LIST_BOOK_ENTRIES = _op(
    OpSpec(
        operation_id="bookActionsListEntries",
        method="GET",
        path_template="/v1/books/{book_id}/entries",
        success_statuses=(200,),
        error_statuses=(400, 401, 404, 422),
        supplied_parameters=(
            ("path", "book_id"),
            ("query", "limit"),
            ("query", "cursor"),
        ),
        response_models=(models.BookEntriesResponse,),
    )
)
LIST_RESOURCES = _op(
    OpSpec(
        operation_id="eventsListResources",
        method="GET",
        path_template="/v1/resources",
        success_statuses=(200,),
        error_statuses=(401, 422),
        supplied_parameters=(
            ("query", "logical_key"),
            ("query", "type"),
            ("query", "tags"),
            ("query", "owner_org_id"),
            ("query", "latest"),
            ("query", "limit"),
            ("query", "cursor"),
        ),
        response_models=(models.ResourceListResponse,),
    )
)
GET_RESOURCE = _op(
    OpSpec(
        operation_id="eventsGetResource",
        method="GET",
        path_template="/v1/resources/{tracking_id}",
        success_statuses=(200,),
        error_statuses=(401, 404, 422),
        supplied_parameters=(("path", "tracking_id"), ("query", "as_of")),
        response_models=(models.ResourceRead,),
    )
)
GET_RESOURCE_DOWNLOAD = _op(
    OpSpec(
        operation_id="eventsGetResourceDownload",
        method="GET",
        path_template="/v1/resources/{tracking_id}/download",
        success_statuses=(200,),
        error_statuses=(401, 403, 404, 422),
        supplied_parameters=(("path", "tracking_id"), ("query", "expires_in")),
        response_models=(models.DownloadResponse,),
    )
)
INVALIDATE_RESOURCE = _op(
    OpSpec(
        operation_id="lineageInvalidateResource",
        method="POST",
        path_template="/v1/resources/{tracking_id}/invalidate",
        success_statuses=(200,),
        error_statuses=(401, 403, 404, 409, 422),
        supplied_parameters=(("path", "tracking_id"),),
        request_model=models.InvalidateRequest,
        response_models=(models.InvalidateResponse,),
    )
)
LIST_VOLUMES = _op(
    OpSpec(
        operation_id="volumesListVolumes",
        method="GET",
        path_template="/v1/volumes",
        success_statuses=(200,),
        error_statuses=(401, 422),
        supplied_parameters=(
            ("query", "limit"),
            ("query", "offset"),
            ("query", "q"),
            ("query", "topic"),
            ("query", "keyword"),
            ("query", "region"),
            ("query", "publisher"),
            ("query", "license"),
            ("query", "coverage_year"),
            ("query", "resource_type"),
            ("query", "deprecated"),
        ),
        response_models=(models.VolumeListResponse,),
    )
)
GET_VOLUME = _op(
    OpSpec(
        operation_id="volumesGetVolume",
        method="GET",
        path_template="/v1/volumes/{volume_name}",
        success_statuses=(200,),
        error_statuses=(401, 404, 422),
        supplied_parameters=(("path", "volume_name"),),
        response_models=(models.VolumeDetailResponse,),
    )
)
CREATE_VOLUME = _op(
    OpSpec(
        operation_id="volumesCreateVolume",
        method="POST",
        path_template="/v1/volumes",
        success_statuses=(201,),
        error_statuses=(401, 403, 409, 422),
        request_model=models.VolumeCreate,
        response_models=(models.VolumeResponse,),
    )
)
UPDATE_VOLUME = _op(
    OpSpec(
        operation_id="volumesUpdateVolume",
        method="PATCH",
        path_template="/v1/volumes/{volume_name}",
        success_statuses=(200,),
        error_statuses=(401, 403, 404, 422),
        supplied_parameters=(("path", "volume_name"),),
        request_model=models.VolumeUpdate,
        response_models=(models.VolumeResponse,),
    )
)
DELETE_VOLUME = _op(
    OpSpec(
        operation_id="volumesDeleteVolume",
        method="DELETE",
        path_template="/v1/volumes/{volume_name}",
        success_statuses=(204,),
        error_statuses=(401, 403, 404, 422),
        supplied_parameters=(("path", "volume_name"),),
    )
)
GET_CATALOGUE_FACETS = _op(
    OpSpec(
        operation_id="catalogueGetCatalogueFacets",
        method="GET",
        path_template="/v1/catalogue/facets",
        success_statuses=(200,),
        error_statuses=(401,),
        response_models=(models.VolumeFacets,),
    )
)
GET_CURRENT_USER = _op(
    OpSpec(
        operation_id="authGetCurrentUser",
        method="GET",
        path_template="/auth/me",
        success_statuses=(200,),
        error_statuses=(401,),
        response_models=(models.UserResponse,),
    )
)
REGISTER_AGENT_IDENTITY = _op(
    OpSpec(
        operation_id="registerAgentIdentity",
        method="POST",
        path_template="/agent/identity",
        success_statuses=(200,),
        error_statuses=(422,),
        request_model=models.AgentIdentityRequest,
        response_models=(
            models.AnonymousRegistrationResponse,
            models.ServiceAuthRegistrationResponse,
        ),
    )
)
AGENT_TOKEN_EXCHANGE = _op(
    OpSpec(
        operation_id="agentTokenExchange",
        method="POST",
        path_template="/oauth2/token",
        success_statuses=(200,),
        error_statuses=(400, 422),
        request_model=models.BodyAgentTokenExchange,
        response_models=(models.TokenResponse,),
    )
)
AGENT_TOKEN_REVOKE = _op(
    OpSpec(
        operation_id="agentTokenRevoke",
        method="POST",
        path_template="/oauth2/revoke",
        success_statuses=(200,),
        error_statuses=(422,),
        request_model=models.BodyAgentTokenRevoke,
    )
)
LIST_RESOURCE_EVENTS = _op(
    OpSpec(
        operation_id="eventsListResourceEvents",
        method="GET",
        path_template="/v1/resources/{tracking_id}/events",
        success_statuses=(200,),
        error_statuses=(400, 401, 404, 422),
        supplied_parameters=(
            ("path", "tracking_id"),
            ("query", "since"),
            ("query", "until"),
            ("query", "limit"),
            ("query", "cursor"),
        ),
        response_models=(models.RegistrationEventsResponse,),
    )
)


def _segment(value: str | UUID) -> str:
    """Quote a path parameter as a single segment, so reserved characters cannot reshape the target."""
    return quote(str(value), safe="")


def _json_body(model: BaseModel) -> Any:
    return model.model_dump(mode="json", exclude_unset=True)


def _params(**candidates: object) -> dict[str, str | int | bool | list[str]]:
    """Drop ``None`` values and coerce the rest to wire-safe query types."""
    params: dict[str, str | int | bool | list[str]] = {}
    for name, value in candidates.items():
        if value is None:
            continue
        if isinstance(value, bool | int | str):
            params[name] = value
        elif isinstance(value, UUID):
            params[name] = str(value)
        elif isinstance(value, Sequence):
            params[name] = [str(item) for item in value]
        else:
            params[name] = str(value)
    return params


def _check(op: OpSpec, response: ApiResponse) -> ApiResponse:
    """Gate every parse on the op's declared statuses, raising the typed hierarchy otherwise."""
    if response.status_code in op.success_statuses:
        return response
    raise errors.error_from_response(
        response,
        declared=response.status_code in op.error_statuses,
        request_method=op.method,
        request_url=op.path_template,
    )


def _restore_utc_fields(payload: dict[str, Any], fields: Sequence[str]) -> None:
    """Restore the UTC wire invariant for naive ASGI harness timestamps."""
    for field in fields:
        value = payload.get(field)
        if isinstance(value, str) and datetime.fromisoformat(value).tzinfo is None:
            payload[field] = f"{value}Z"


def build_register_resources(request: models.RegisterResourcesRequest) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path=REGISTER_RESOURCES.path_template,
        json_body=_json_body(request),
    )


def parse_register_resources(response: ApiResponse) -> models.RegisterResourcesResponse:
    _check(REGISTER_RESOURCES, response)
    return models.RegisterResourcesResponse.model_validate_json(response.content)


def build_initiate_ingest_upload(request: models.IngestUploadInitiateRequest) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path=INITIATE_INGEST_UPLOAD.path_template,
        json_body=_json_body(request),
    )


def parse_initiate_ingest_upload(
    response: ApiResponse,
) -> models.UploadInitiateResponse | models.UploadAlreadyExistsResponse:
    """Discriminate the two success arms: presigned parts, or the dedupe short-circuit."""
    _check(INITIATE_INGEST_UPLOAD, response)
    try:
        return models.UploadAlreadyExistsResponse.model_validate_json(response.content)
    except ValueError:
        return models.UploadInitiateResponse.model_validate_json(response.content)


def build_complete_ingest_upload(request: models.IngestUploadCompleteRequest) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path=COMPLETE_INGEST_UPLOAD.path_template,
        json_body=_json_body(request),
    )


def parse_complete_ingest_upload(response: ApiResponse) -> None:
    _check(COMPLETE_INGEST_UPLOAD, response)


def build_put_presigned(url: str, content: bytes, *, content_type: str | None = None) -> ApiRequest:
    """Raw object-storage PUT to a presigned URL. Not an API op, so it bypasses the registry."""
    headers = {"content-type": content_type} if content_type else {}
    return ApiRequest(
        method="PUT",
        path="",
        absolute_url=url,
        headers=headers,
        content=content,
    )


def parse_put_presigned(response: ApiResponse) -> str | None:
    """Return the part ETag object storage answered with."""
    if response.status_code // 100 != 2:
        raise errors.error_from_response(response, declared=False, request_method="PUT")
    return response.headers.get("etag")


def build_query_resource_data(
    tracking_id: str | UUID,
    *,
    format: DataFormat = "parquet",
    select: str | None = None,
    order: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    filters: Mapping[str, str] | None = None,
    if_none_match: str | None = None,
) -> ApiRequest:
    """``/data`` with ``Accept``-header format negotiation.

    ``filters`` carries the dynamic ``col.op`` modifiers, which are per-resource
    and therefore unstatable in the contract.
    """
    params = _params(select=select, order=order, limit=limit, offset=offset)
    for name, value in (filters or {}).items():
        params[name] = value
    headers = {"accept": ACCEPT_BY_FORMAT[format]}
    if if_none_match is not None:
        headers["if-none-match"] = if_none_match
    return ApiRequest(
        method="GET",
        path=QUERY_RESOURCE_DATA.path_template.format(tracking_id=_segment(tracking_id)),
        params=params,
        headers=headers,
    )


def parse_query_resource_data(response: ApiResponse) -> DataPayload | NotModified:
    _check(QUERY_RESOURCE_DATA, response)
    etag = response.headers.get("etag")
    if response.status_code == 304:
        return NotModified(etag=etag)
    media_type = response.media_type
    fmt = FORMAT_BY_MEDIA_TYPE.get(media_type)
    if fmt is None:
        raise errors.UnexpectedResponseError(
            f"undeclared /data media type {media_type!r}",
            status_code=response.status_code,
            request_method=QUERY_RESOURCE_DATA.method,
            request_url=QUERY_RESOURCE_DATA.path_template,
        )
    return DataPayload(format=fmt, content=response.content, etag=etag)


def build_get_book_resource_timeseries(
    book_id: str | UUID,
    resource_name: str,
    *,
    drop: Sequence[str] | None = None,
    limit: int | None = None,
    top_n: int | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    filters: Mapping[str, str | list[str]] | None = None,
) -> ApiRequest:
    params = _params(
        drop=drop,
        limit=limit,
        top_n=top_n,
        **{"year.min": year_min, "year.max": year_max},
    )
    params.update(filters or {})
    return ApiRequest(
        method="GET",
        path=GET_BOOK_RESOURCE_TIMESERIES.path_template.format(
            book_id=_segment(book_id),
            resource_name=_segment(resource_name),
        ),
        params=params,
    )


def parse_get_book_resource_timeseries(response: ApiResponse) -> models.TimeseriesResponse:
    _check(GET_BOOK_RESOURCE_TIMESERIES, response)
    return models.TimeseriesResponse.model_validate_json(response.content)


def build_get_book_resource_facets(
    book_id: str | UUID,
    resource_name: str,
    *,
    max_values: int | None = None,
    filters: Mapping[str, str] | None = None,
) -> ApiRequest:
    params = _params(max_values=max_values)
    params.update(filters or {})
    return ApiRequest(
        method="GET",
        path=GET_BOOK_RESOURCE_FACETS.path_template.format(
            book_id=_segment(book_id),
            resource_name=_segment(resource_name),
        ),
        params=params,
    )


def parse_get_book_resource_facets(response: ApiResponse) -> models.FacetsResponse:
    _check(GET_BOOK_RESOURCE_FACETS, response)
    return models.FacetsResponse.model_validate_json(response.content)


def build_get_book_resource_preview(
    book_id: str | UUID,
    resource_name: str,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=GET_BOOK_RESOURCE_PREVIEW.path_template.format(
            book_id=_segment(book_id),
            resource_name=_segment(resource_name),
        ),
        params=_params(limit=limit, offset=offset),
    )


def parse_get_book_resource_preview(response: ApiResponse) -> models.PreviewResponse:
    _check(GET_BOOK_RESOURCE_PREVIEW, response)
    return models.PreviewResponse.model_validate_json(response.content)


def build_get_book_resource_schema(
    book_id: str | UUID,
    resource_name: str,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=GET_BOOK_RESOURCE_SCHEMA.path_template.format(
            book_id=_segment(book_id),
            resource_name=_segment(resource_name),
        ),
        params=_params(limit=limit, offset=offset),
    )


def parse_get_book_resource_schema(response: ApiResponse) -> models.TimeseriesMetadataResponse:
    _check(GET_BOOK_RESOURCE_SCHEMA, response)
    return models.TimeseriesMetadataResponse.model_validate_json(response.content)


def build_get_url(url: str) -> ApiRequest:
    """Build an unauthenticated GET to an API-issued content URL."""
    return ApiRequest(method="GET", path="", absolute_url=url)


def parse_get_url(response: ApiResponse) -> bytes:
    """Return successful content bytes from an API-issued URL."""
    if response.status_code // 100 != 2:
        raise errors.error_from_response(response, declared=False, request_method="GET")
    return response.content


def build_draft_book(request: models.BookDraftRequest) -> ApiRequest:
    return ApiRequest(method="POST", path=DRAFT_BOOK.path_template, json_body=_json_body(request))


def parse_draft_book(response: ApiResponse) -> models.BookDetail:
    _check(DRAFT_BOOK, response)
    payload = json.loads(response.content)
    _restore_utc_fields(payload, ("created_at", "published_at", "invalidated_at"))
    return models.BookDetail.model_validate(payload)


def build_attach_entry(book_id: str, request: models.BookEntryAttach) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path=ATTACH_ENTRY.path_template.format(book_id=_segment(book_id)),
        json_body=_json_body(request),
    )


def parse_attach_entry(response: ApiResponse) -> models.BookEntryAttachResponse:
    _check(ATTACH_ENTRY, response)
    return models.BookEntryAttachResponse.model_validate_json(response.content)


def build_publish_book(book_id: str) -> ApiRequest:
    return ApiRequest(
        method="POST", path=PUBLISH_BOOK.path_template.format(book_id=_segment(book_id))
    )


def parse_publish_book(response: ApiResponse) -> models.BookDetail:
    _check(PUBLISH_BOOK, response)
    payload = json.loads(response.content)
    _restore_utc_fields(payload, ("created_at", "published_at", "invalidated_at"))
    return models.BookDetail.model_validate(payload)


def build_list_books(
    *,
    volume: str | None = None,
    version: str | None = None,
    status: str | None = None,
    latest_only: bool | None = None,
    producer_version: str | None = None,
    config_hash: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=LIST_BOOKS.path_template,
        params=_params(
            volume=volume,
            version=version,
            status=status,
            latest_only=latest_only,
            producer_version=producer_version,
            config_hash=config_hash,
            limit=limit,
            offset=offset,
        ),
    )


def parse_list_books(response: ApiResponse) -> models.BookListResponse:
    _check(LIST_BOOKS, response)
    payload = json.loads(response.content)
    for item in payload.get("items", []):
        _restore_utc_fields(item, ("created_at", "published_at"))
    return models.BookListResponse.model_validate(payload)


def build_get_book(book_id: str) -> ApiRequest:
    return ApiRequest(method="GET", path=GET_BOOK.path_template.format(book_id=_segment(book_id)))


def parse_get_book(response: ApiResponse) -> models.BookResponse:
    _check(GET_BOOK, response)
    payload = json.loads(response.content)
    _restore_utc_fields(payload, ("created_at", "updated_at", "published_at", "invalidated_at"))
    return models.BookResponse.model_validate(payload)


def build_update_book(book_id: str, request: models.BookUpdate) -> ApiRequest:
    return ApiRequest(
        method="PATCH",
        path=UPDATE_BOOK.path_template.format(book_id=_segment(book_id)),
        json_body=_json_body(request),
    )


def parse_update_book(response: ApiResponse) -> models.BookResponse:
    """Parse the updated book. Only a draft is updatable, so a published book fails here."""
    _check(UPDATE_BOOK, response)
    payload = json.loads(response.content)
    _restore_utc_fields(payload, ("created_at", "updated_at", "published_at", "invalidated_at"))
    return models.BookResponse.model_validate(payload)


def build_delete_book(book_id: str) -> ApiRequest:
    return ApiRequest(
        method="DELETE",
        path=DELETE_BOOK.path_template.format(book_id=_segment(book_id)),
    )


def parse_delete_book(response: ApiResponse) -> None:
    """Confirm the draft is gone. A published book is protected, and arrives as an error."""
    _check(DELETE_BOOK, response)


def build_list_book_entries(
    book_id: str,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=LIST_BOOK_ENTRIES.path_template.format(book_id=_segment(book_id)),
        params=_params(limit=limit, cursor=cursor),
    )


def parse_list_book_entries(response: ApiResponse) -> models.BookEntriesResponse:
    _check(LIST_BOOK_ENTRIES, response)
    return models.BookEntriesResponse.model_validate_json(response.content)


def build_list_resources(
    *,
    logical_key: str | None = None,
    type: str | None = None,
    tags: Sequence[str] | None = None,
    owner_org_id: str | None = None,
    latest: bool | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=LIST_RESOURCES.path_template,
        params=_params(
            logical_key=logical_key,
            type=type,
            tags=tags,
            owner_org_id=owner_org_id,
            latest=latest,
            limit=limit,
            cursor=cursor,
        ),
    )


def parse_list_resources(response: ApiResponse) -> models.ResourceListResponse:
    _check(LIST_RESOURCES, response)
    return models.ResourceListResponse.model_validate_json(response.content)


def build_get_resource(tracking_id: str | UUID, *, as_of: str | None = None) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=GET_RESOURCE.path_template.format(tracking_id=_segment(tracking_id)),
        params=_params(as_of=as_of),
    )


def parse_get_resource(response: ApiResponse) -> models.ResourceRead:
    _check(GET_RESOURCE, response)
    payload = json.loads(response.content)
    _restore_utc_fields(payload, ("created_at", "updated_at"))
    return models.ResourceRead.model_validate(payload)


def build_get_resource_download(
    tracking_id: str | UUID, *, expires_in: int | None = None
) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=GET_RESOURCE_DOWNLOAD.path_template.format(tracking_id=_segment(tracking_id)),
        params=_params(expires_in=expires_in),
    )


def parse_get_resource_download(response: ApiResponse) -> models.DownloadResponse:
    _check(GET_RESOURCE_DOWNLOAD, response)
    return models.DownloadResponse.model_validate_json(response.content)


def build_invalidate_resource(
    tracking_id: str | UUID, request: models.InvalidateRequest
) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path=INVALIDATE_RESOURCE.path_template.format(tracking_id=_segment(tracking_id)),
        json_body=_json_body(request),
    )


def parse_invalidate_resource(response: ApiResponse) -> models.InvalidateResponse:
    _check(INVALIDATE_RESOURCE, response)
    return models.InvalidateResponse.model_validate_json(response.content)


def build_list_resource_events(
    tracking_id: str | UUID,
    *,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=LIST_RESOURCE_EVENTS.path_template.format(tracking_id=_segment(tracking_id)),
        params=_params(since=since, until=until, limit=limit, cursor=cursor),
    )


def parse_list_resource_events(response: ApiResponse) -> models.RegistrationEventsResponse:
    _check(LIST_RESOURCE_EVENTS, response)
    return models.RegistrationEventsResponse.model_validate_json(response.content)


def build_list_volumes(
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
) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=LIST_VOLUMES.path_template,
        params=_params(
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
        ),
    )


def parse_list_volumes(response: ApiResponse) -> models.VolumeListResponse:
    _check(LIST_VOLUMES, response)
    payload = json.loads(response.content)
    for item in payload.get("items", []):
        _restore_utc_fields(item, ("created_at", "updated_at"))
    return models.VolumeListResponse.model_validate(payload)


def build_get_volume(volume_name: str) -> ApiRequest:
    return ApiRequest(
        method="GET",
        path=GET_VOLUME.path_template.format(volume_name=_segment(volume_name)),
    )


def parse_get_volume(response: ApiResponse) -> models.VolumeDetailResponse:
    _check(GET_VOLUME, response)
    payload = json.loads(response.content)
    _restore_utc_fields(payload, ("created_at", "updated_at"))
    for version in payload.get("versions", []):
        for edition in version.get("editions", []):
            _restore_utc_fields(edition, ("created_at", "published_at"))
    return models.VolumeDetailResponse.model_validate(payload)


def build_create_volume(request: models.VolumeCreate) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path=CREATE_VOLUME.path_template,
        json_body=_json_body(request),
    )


def parse_create_volume(response: ApiResponse) -> models.VolumeResponse:
    _check(CREATE_VOLUME, response)
    payload = json.loads(response.content)
    _restore_utc_fields(payload, ("created_at", "updated_at"))
    return models.VolumeResponse.model_validate(payload)


def build_update_volume(volume_name: str, request: models.VolumeUpdate) -> ApiRequest:
    return ApiRequest(
        method="PATCH",
        path=UPDATE_VOLUME.path_template.format(volume_name=_segment(volume_name)),
        json_body=_json_body(request),
    )


def parse_update_volume(response: ApiResponse) -> models.VolumeResponse:
    _check(UPDATE_VOLUME, response)
    payload = json.loads(response.content)
    _restore_utc_fields(payload, ("created_at", "updated_at"))
    return models.VolumeResponse.model_validate(payload)


def build_delete_volume(volume_name: str) -> ApiRequest:
    return ApiRequest(
        method="DELETE",
        path=DELETE_VOLUME.path_template.format(volume_name=_segment(volume_name)),
    )


def parse_delete_volume(response: ApiResponse) -> None:
    """Confirm the volume and its books are gone. Deletion needs ADMIN, where creation needs WRITE."""
    _check(DELETE_VOLUME, response)


def build_get_catalogue_facets() -> ApiRequest:
    return ApiRequest(method="GET", path=GET_CATALOGUE_FACETS.path_template)


def parse_get_catalogue_facets(response: ApiResponse) -> models.VolumeFacets:
    _check(GET_CATALOGUE_FACETS, response)
    return models.VolumeFacets.model_validate_json(response.content)


def build_get_current_user() -> ApiRequest:
    return ApiRequest(method="GET", path=GET_CURRENT_USER.path_template)


def parse_get_current_user(response: ApiResponse) -> models.UserResponse:
    _check(GET_CURRENT_USER, response)
    return models.UserResponse.model_validate_json(response.content)


def build_register_agent_identity(request: models.AgentIdentityRequest) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path=REGISTER_AGENT_IDENTITY.path_template,
        json_body=_json_body(request),
    )


def parse_register_agent_identity(
    response: ApiResponse,
) -> models.AnonymousRegistrationResponse | models.ServiceAuthRegistrationResponse:
    """Discriminate the two registration arms on ``registration_type``."""
    _check(REGISTER_AGENT_IDENTITY, response)
    payload = json.loads(response.content)
    _restore_utc_fields(payload, ("assertion_expires", "claim_token_expires"))
    if payload.get("registration_type") == "service_auth":
        return models.ServiceAuthRegistrationResponse.model_validate(payload)
    return models.AnonymousRegistrationResponse.model_validate(payload)


def _oauth_protocol_error(op: OpSpec, response: ApiResponse) -> errors.OAuthProtocolError | None:
    """Map an OAuth ``{"error": ...}`` body to its typed exception, or ``None``."""
    try:
        body = json.loads(response.content)
    except ValueError:
        return None
    if not isinstance(body, dict) or not isinstance(body.get("error"), str):
        return None
    return errors.OAuthProtocolError(
        str(body.get("error_description") or body["error"]),
        error=body["error"],
        status_code=response.status_code,
        request_method=op.method,
        request_url=op.path_template,
    )


def _form_body(model: BaseModel) -> dict[str, str]:
    """Dump a request model as a URL-encoded form, dropping unset non-string fields."""
    return {
        name: value
        for name, value in model.model_dump(mode="json").items()
        if isinstance(value, str)
    }


def build_agent_token_exchange(request: models.BodyAgentTokenExchange) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path=AGENT_TOKEN_EXCHANGE.path_template,
        form_body=_form_body(request),
    )


def parse_agent_token_exchange(response: ApiResponse) -> models.TokenResponse:
    """Parse a token grant, raising the typed OAuth error on protocol rejections.

    ``authorization_pending`` and friends arrive as an OAuth error body rather
    than problem+json, and claim-grant polling dispatches on the error code.
    """
    if response.status_code not in AGENT_TOKEN_EXCHANGE.success_statuses:
        oauth_error = _oauth_protocol_error(AGENT_TOKEN_EXCHANGE, response)
        if oauth_error is not None:
            raise oauth_error
    _check(AGENT_TOKEN_EXCHANGE, response)
    payload = json.loads(response.content)
    _restore_utc_fields(payload, ("assertion_expires",))
    return models.TokenResponse.model_validate(payload)


def build_agent_token_revoke(request: models.BodyAgentTokenRevoke) -> ApiRequest:
    return ApiRequest(
        method="POST",
        path=AGENT_TOKEN_REVOKE.path_template,
        form_body=_form_body(request),
    )


def parse_agent_token_revoke(response: ApiResponse) -> None:
    _check(AGENT_TOKEN_REVOKE, response)
