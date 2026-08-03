"""Fixture-driven unit tests for the I/O-free ``build_*``/``parse_*`` core."""

from typing import Any
from uuid import UUID

import pytest

from bookshelf._core import errors, ops
from bookshelf._core.types import ApiRequest, DataPayload, NotModified
from bookshelf._generated import models
from tests import _core_payloads as payloads

TRACKING_ID = UUID("0197a000-0000-7000-8000-000000000001")


def test_registry_covers_the_used_surface() -> None:
    assert len(ops.OP_REGISTRY) == 31
    assert len({(op.method, op.path_template) for op in ops.OP_REGISTRY.values()}) == 31


def test_build_register_resources_dumps_set_fields_only() -> None:
    request = models.RegisterResourcesRequest(
        items=[models.RegisterResourceItem(type=models.ResourceType.binary)]
    )
    req = ops.build_register_resources(request)
    assert req.method == "POST"
    assert req.path == "/v1/resources/registrations"
    assert req.json_body == {"items": [{"type": "binary"}]}


def test_build_query_resource_data_negotiates_format_and_filters() -> None:
    req = ops.build_query_resource_data(
        TRACKING_ID,
        format="parquet",
        select="region,year",
        order="-year",
        limit=10,
        offset=5,
        filters={"year.gte": "2000"},
        if_none_match='"abc"',
    )
    assert req.method == "GET"
    assert req.path == f"/v1/resources/{TRACKING_ID}/data"
    assert req.headers["accept"] == "application/parquet"
    assert req.headers["if-none-match"] == '"abc"'
    assert req.params == {
        "select": "region,year",
        "order": "-year",
        "limit": 10,
        "offset": 5,
        "year.gte": "2000",
    }


def test_build_query_resource_data_csv_and_json_accept() -> None:
    assert ops.build_query_resource_data(TRACKING_ID, format="csv").headers["accept"] == "text/csv"
    assert (
        ops.build_query_resource_data(TRACKING_ID, format="json").headers["accept"]
        == "application/json"
    )


def test_build_list_resources_drops_none_and_coerces_sequences() -> None:
    req = ops.build_list_resources(
        logical_key="emissions/co2",
        type="timeseries",
        tags=["climate", "emissions"],
        owner_org_id=None,
        latest=True,
        limit=25,
        cursor="next",
    )
    assert req.params == {
        "logical_key": "emissions/co2",
        "type": "timeseries",
        "tags": ["climate", "emissions"],
        "latest": True,
        "limit": 25,
        "cursor": "next",
    }
    assert "owner_org_id" not in req.params


def test_build_put_presigned_is_absolute_and_registry_free() -> None:
    req = ops.build_put_presigned("https://s3.example/part1?sig=abc", b"bytes")
    assert req.absolute_url == "https://s3.example/part1?sig=abc"
    assert req.content == b"bytes"
    assert all(op.path_template != "" for op in ops.OP_REGISTRY.values())


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (
            ops.build_initiate_ingest_upload(
                models.IngestUploadInitiateRequest(
                    hash="sha256:" + "0" * 64,
                    size_bytes=10,
                )
            ),
            ApiRequest(
                method="POST",
                path="/v1/resources/uploads",
                json_body={"hash": "sha256:" + "0" * 64, "size_bytes": 10},
            ),
        ),
        (
            ops.build_complete_ingest_upload(
                models.IngestUploadCompleteRequest(upload_id="upload-1", storage_path="ingest/key")
            ),
            ApiRequest(
                method="POST",
                path="/v1/resources/uploads/complete",
                json_body={"upload_id": "upload-1", "storage_path": "ingest/key"},
            ),
        ),
        (
            ops.build_draft_book(models.BookDraftRequest(version="1.0", series_name="series")),
            ApiRequest(
                method="POST",
                path="/v1/books",
                json_body={"version": "1.0", "series_name": "series"},
            ),
        ),
        (
            ops.build_attach_entry(
                "book/one",
                models.BookEntryAttach(tracking_id=TRACKING_ID, name_in_book="table"),
            ),
            ApiRequest(
                method="POST",
                path="/v1/books/book%2Fone/entries",
                json_body={"tracking_id": str(TRACKING_ID), "name_in_book": "table"},
            ),
        ),
        (
            ops.build_publish_book("book/one"),
            ApiRequest(method="POST", path="/v1/books/book%2Fone/publish"),
        ),
        (
            ops.build_list_books(
                volume="series",
                version="1.0",
                status="published",
                latest_only=True,
                producer_version="2.0",
                config_hash="sha256:abc",
                limit=20,
                offset=40,
            ),
            ApiRequest(
                method="GET",
                path="/v1/books",
                params={
                    "volume": "series",
                    "version": "1.0",
                    "status": "published",
                    "latest_only": True,
                    "producer_version": "2.0",
                    "config_hash": "sha256:abc",
                    "limit": 20,
                    "offset": 40,
                },
            ),
        ),
        (
            ops.build_get_book("book/one"),
            ApiRequest(method="GET", path="/v1/books/book%2Fone"),
        ),
        (
            ops.build_list_book_entries("book/one", limit=20, cursor="next"),
            ApiRequest(
                method="GET",
                path="/v1/books/book%2Fone/entries",
                params={"limit": 20, "cursor": "next"},
            ),
        ),
        (
            ops.build_update_book("book/one", models.BookUpdate(metadata={"note": "fixed"})),
            ApiRequest(
                method="PATCH",
                path="/v1/books/book%2Fone",
                json_body={"metadata": {"note": "fixed"}},
            ),
        ),
        (
            ops.build_delete_book("book/one"),
            ApiRequest(method="DELETE", path="/v1/books/book%2Fone"),
        ),
        (
            ops.build_create_volume(models.VolumeCreate(name="example", license="MIT")),
            ApiRequest(
                method="POST",
                path="/v1/volumes",
                json_body={"name": "example", "license": "MIT"},
            ),
        ),
        (
            ops.build_update_volume(
                "example/one",
                models.VolumeUpdate(description=models.Description3(root="now with units")),
            ),
            ApiRequest(
                method="PATCH",
                path="/v1/volumes/example%2Fone",
                json_body={"description": "now with units"},
            ),
        ),
        (
            ops.build_delete_volume("example/one"),
            ApiRequest(method="DELETE", path="/v1/volumes/example%2Fone"),
        ),
        (
            ops.build_get_resource(TRACKING_ID, as_of="2026-01-01T00:00:00Z"),
            ApiRequest(
                method="GET",
                path=f"/v1/resources/{TRACKING_ID}",
                params={"as_of": "2026-01-01T00:00:00Z"},
            ),
        ),
        (
            ops.build_get_resource_download(TRACKING_ID, expires_in=300),
            ApiRequest(
                method="GET",
                path=f"/v1/resources/{TRACKING_ID}/download",
                params={"expires_in": 300},
            ),
        ),
        (
            ops.build_invalidate_resource(
                TRACKING_ID, models.InvalidateRequest(reason="bad units")
            ),
            ApiRequest(
                method="POST",
                path=f"/v1/resources/{TRACKING_ID}/invalidate",
                json_body={"reason": "bad units"},
            ),
        ),
        (
            ops.build_list_resource_events(
                TRACKING_ID,
                since="2026-01-01T00:00:00Z",
                until="2026-02-01T00:00:00Z",
                limit=20,
                cursor="next",
            ),
            ApiRequest(
                method="GET",
                path=f"/v1/resources/{TRACKING_ID}/events",
                params={
                    "since": "2026-01-01T00:00:00Z",
                    "until": "2026-02-01T00:00:00Z",
                    "limit": 20,
                    "cursor": "next",
                },
            ),
        ),
    ],
)
def test_build_pairs_shape_requests(actual: ApiRequest, expected: ApiRequest) -> None:
    assert actual == expected


_PARSE_PAIR_CASES: list[tuple[Any, int, dict[str, Any], type[Any]]] = [
    (ops.parse_register_resources, 200, payloads.REGISTERED, models.RegisterResourcesResponse),
    (ops.parse_draft_book, 201, payloads.BOOK_DETAIL, models.BookDetail),
    (ops.parse_attach_entry, 201, payloads.ENTRY_ATTACHED, models.BookEntryAttachResponse),
    (ops.parse_publish_book, 200, payloads.BOOK_DETAIL, models.BookDetail),
    (ops.parse_list_books, 200, payloads.BOOK_LIST, models.BookListResponse),
    (ops.parse_get_book, 200, payloads.BOOK_RESPONSE, models.BookResponse),
    (ops.parse_update_book, 200, payloads.BOOK_RESPONSE, models.BookResponse),
    (ops.parse_create_volume, 201, payloads.VOLUME, models.VolumeResponse),
    (ops.parse_update_volume, 200, payloads.VOLUME, models.VolumeResponse),
    (ops.parse_list_book_entries, 200, payloads.BOOK_ENTRIES, models.BookEntriesResponse),
    (ops.parse_list_resources, 200, payloads.RESOURCE_LIST, models.ResourceListResponse),
    (ops.parse_get_resource, 200, payloads.RESOURCE_READ, models.ResourceRead),
    (ops.parse_get_resource_download, 200, payloads.DOWNLOAD, models.DownloadResponse),
    (ops.parse_invalidate_resource, 200, payloads.INVALIDATED, models.InvalidateResponse),
    (
        ops.parse_list_resource_events,
        200,
        payloads.RESOURCE_EVENTS,
        models.RegistrationEventsResponse,
    ),
]


@pytest.mark.parametrize(
    ("parse", "status", "payload", "model_type"),
    _PARSE_PAIR_CASES,
    ids=[case[0].__name__ for case in _PARSE_PAIR_CASES],
)
def test_parse_pairs_return_typed_models(
    parse: Any, status: int, payload: dict[str, Any], model_type: type[Any]
) -> None:
    parsed = parse(payloads.json_response(status, payload))
    assert isinstance(parsed, model_type)


def test_parse_initiate_upload_discriminates_both_arms() -> None:
    parts = ops.parse_initiate_ingest_upload(payloads.json_response(200, payloads.UPLOAD_INITIATED))
    assert isinstance(parts, models.UploadInitiateResponse)
    assert parts.parts[0].part_number == 1

    exists = ops.parse_initiate_ingest_upload(payloads.json_response(200, payloads.UPLOAD_EXISTS))
    assert isinstance(exists, models.UploadAlreadyExistsResponse)
    assert exists.already_exists is True


def test_parse_complete_upload_accepts_204() -> None:
    assert ops.parse_complete_ingest_upload(payloads.empty_response(204)) is None


def test_parse_deletions_accept_204() -> None:
    assert ops.parse_delete_book(payloads.empty_response(204)) is None
    assert ops.parse_delete_volume(payloads.empty_response(204)) is None


def test_parse_delete_book_rejects_a_published_book() -> None:
    """The API protects a published book, and the refusal arrives as a declared 400."""
    problem = {
        "type": "https://bookshelf.test/problems/400",
        "title": "Cannot delete",
        "status": 400,
        "detail": "only draft books can be deleted",
    }
    response = payloads.json_response(400, problem, media_type="application/problem+json")

    with pytest.raises(errors.ValidationError) as excinfo:
        ops.parse_delete_book(response)

    assert excinfo.value.detail == "only draft books can be deleted"


def test_parse_create_volume_restores_the_utc_wire_invariant() -> None:
    naive = dict(
        payloads.VOLUME, created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00"
    )

    volume = ops.parse_create_volume(payloads.json_response(201, naive))

    assert volume.created_at.tzinfo is not None
    assert volume.updated_at.tzinfo is not None


def test_parse_put_presigned_returns_etag() -> None:
    assert ops.parse_put_presigned(payloads.empty_response(200, {"etag": '"p1"'})) == '"p1"'
    with pytest.raises(errors.ServerError):
        ops.parse_put_presigned(payloads.empty_response(500))


def test_parse_query_resource_data_payload_and_not_modified() -> None:
    response = payloads.json_response(200, [{"year": 2000}], headers={"etag": '"abc"'})
    parsed = ops.parse_query_resource_data(response)
    assert parsed == DataPayload(format="json", content=response.content, etag='"abc"')

    not_modified = ops.parse_query_resource_data(payloads.empty_response(304, {"etag": '"abc"'}))
    assert not_modified == NotModified(etag='"abc"')


def test_parse_query_resource_data_rejects_undeclared_media_type() -> None:
    response = payloads.json_response(200, "nope", media_type="text/html")
    with pytest.raises(errors.UnexpectedResponseError):
        ops.parse_query_resource_data(response)


def test_declared_problem_maps_to_typed_exception() -> None:
    response = payloads.json_response(
        409, payloads.PROBLEM_CONFLICT, media_type="application/problem+json"
    )
    with pytest.raises(errors.ConflictError) as excinfo:
        ops.parse_register_resources(response)
    assert excinfo.value.detail == payloads.PROBLEM_CONFLICT["detail"]
    assert excinfo.value.problem is not None
    assert excinfo.value.problem.status == 409
    assert excinfo.value.request_url == "/v1/resources/registrations"


@pytest.mark.parametrize(
    ("status", "exception_type"),
    [
        (400, errors.ValidationError),
        (401, errors.AuthenticationError),
        (403, errors.ForbiddenError),
        (404, errors.NotFoundError),
        (409, errors.ConflictError),
        (422, errors.ValidationError),
    ],
)
def test_problem_json_maps_the_exception_hierarchy(
    status: int, exception_type: type[errors.APIError]
) -> None:
    problem = {
        "type": f"https://bookshelf.test/problems/{status}",
        "title": "Request failed",
        "status": status,
        "detail": f"failure {status}",
    }
    response = payloads.json_response(status, problem, media_type="application/problem+json")

    with pytest.raises(exception_type) as excinfo:
        ops.parse_register_resources(response)

    assert excinfo.value.problem == models.Problem.model_validate(problem)
    assert excinfo.value.detail == f"failure {status}"


def test_undeclared_status_maps_to_unexpected_response() -> None:
    # 409 is not declared for uploadsInitiateIngestUpload.
    response = payloads.json_response(
        409, payloads.PROBLEM_CONFLICT, media_type="application/problem+json"
    )
    with pytest.raises(errors.UnexpectedResponseError):
        ops.parse_initiate_ingest_upload(response)


def test_5xx_maps_to_server_error_with_fallback_detail() -> None:
    response = payloads.empty_response(502)
    with pytest.raises(errors.ServerError) as excinfo:
        ops.parse_get_book(response)
    assert excinfo.value.status_code == 502
    assert excinfo.value.detail == "no response body"


def test_fastapi_validation_body_falls_back_to_detail_field() -> None:
    response = payloads.json_response(422, {"detail": [{"loc": ["query", "limit"]}]})
    with pytest.raises(errors.ValidationError) as excinfo:
        ops.parse_list_books(response)
    assert "limit" in excinfo.value.detail


def test_batch_item_errors_surface_on_the_exception() -> None:
    problem = dict(payloads.PROBLEM_CONFLICT, errors=[{"status": 409, "detail": "item 3 clashed"}])
    response = payloads.json_response(409, problem, media_type="application/problem+json")
    with pytest.raises(errors.ConflictError) as excinfo:
        ops.parse_register_resources(response)
    assert excinfo.value.errors == [{"status": 409, "detail": "item 3 clashed"}]
    assert excinfo.value.item_errors == [models.ItemError(status=409, detail="item 3 clashed")]
