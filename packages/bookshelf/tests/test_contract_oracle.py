"""Schema drift oracle for the hand-written SDK transport registry."""

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin

import pytest
from pydantic import BaseModel

from bookshelf._core import ops

SDK_ROOT = Path(__file__).resolve().parents[1]
DATA_MEDIA_TYPES = frozenset({"application/json", "text/csv", "application/parquet"})

# The hardened contract contains more operations than the SDK intentionally uses.
# Keeping the complete baseline lets a newly added operation warn without treating the
# existing server-only surface as perpetual drift.
KNOWN_OPERATION_IDS = frozenset(
    {
        "agentTokenExchange",
        "agentTokenRevoke",
        "authGetCurrentUser",
        "authGetSession",
        "bookActionsAttachEntry",
        "bookActionsDraftBook",
        "bookActionsInvalidateBook",
        "bookActionsListBookEvents",
        "bookActionsListEntries",
        "bookActionsPublishBook",
        "booksCreateBook",
        "booksDeleteBook",
        "booksGetBook",
        "booksListBooks",
        "booksUpdateBook",
        "dataQueryResourceData",
        "eventsGetResource",
        "eventsGetResourceDownload",
        "eventsListEvents",
        "eventsListResourceEvents",
        "eventsListResourceLocations",
        "eventsListResources",
        "explorerCreateChart",
        "explorerDeleteChart",
        "explorerForkChart",
        "explorerGetChart",
        "explorerListCharts",
        "explorerUpdateChart",
        "healthLiveCheck",
        "healthReadyCheck",
        "lineageBookProv",
        "lineageInvalidateResource",
        "lineageResourceDownstream",
        "lineageResourceDownstreamEntries",
        "lineageResourceProv",
        "lineageResourceUpstream",
        "lineageReviseResource",
        "logsIngestLogs",
        "publicResolverResolvePublicUrl",
        "registerAgentIdentity",
        "registrationsRegisterResources",
        "registrationsRegisterResourcesBulk",
        "resourcesCompleteUpload",
        "resourcesCreateResource",
        "resourcesDeleteResource",
        "resourcesGetDownloadUrl",
        "resourcesGetResource",
        "resourcesGetResourceFacets",
        "resourcesGetResourcePreview",
        "resourcesGetResourceTimeseries",
        "resourcesGetTimeseriesMetadata",
        "resourcesInitiateUpload",
        "resourcesListResources",
        "startAgentClaim",
        "uploadsCompleteIngestUpload",
        "uploadsInitiateIngestUpload",
        "verifyAgentClaim",
        "volumesCreateVolume",
        "volumesDeleteVolume",
        "volumesGetVolume",
        "volumesListVolumes",
        "volumesUpdateVolume",
    }
)


@dataclass(frozen=True, slots=True)
class ContractAudit:
    """Wrong-making drift and additive drift found by the oracle."""

    failures: tuple[str, ...]
    warnings: tuple[str, ...]


class AdditiveContractDriftWarning(UserWarning):
    """The API grew in a way the SDK can safely adopt later."""


def _operations(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            found[operation["operationId"]] = {
                "method": method.upper(),
                "path": path,
                "path_parameters": path_item.get("parameters", []),
                **operation,
            }
    return found


def _schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    node: Any = spec
    for part in reference.removeprefix("#/").split("/"):
        if part:
            node = node[part]
    return node


def _parameter_key(parameter: dict[str, Any]) -> tuple[str, str]:
    location = parameter["in"]
    name = parameter["name"].lower() if location == "header" else parameter["name"]
    return location, name


def _is_nullable(
    spec: dict[str, Any],
    schema: dict[str, Any],
    seen_references: frozenset[str] = frozenset(),
) -> bool:
    reference = schema.get("$ref")
    if reference is not None:
        if reference in seen_references:
            return False
        return _is_nullable(
            spec,
            _schema(spec, schema),
            seen_references | {reference},
        )
    schema_type = schema.get("type")
    if schema_type == "null" or (isinstance(schema_type, list) and "null" in schema_type):
        return True
    alternatives = schema.get("anyOf") or schema.get("oneOf") or []
    return any(_is_nullable(spec, alternative, seen_references) for alternative in alternatives)


def _model_types(annotations: tuple[Any, ...]) -> tuple[type[BaseModel], ...]:
    found: list[type[BaseModel]] = []
    for annotation in annotations:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            found.append(annotation)
            continue
        found.extend(_model_types(get_args(annotation)))
    return tuple(found)


def _array_item_annotations(annotations: tuple[Any, ...]) -> tuple[Any, ...]:
    items: list[Any] = []
    for annotation in annotations:
        origin = get_origin(annotation)
        if origin in (Union, UnionType):
            items.extend(_array_item_annotations(get_args(annotation)))
        elif origin is not None:
            items.extend(get_args(annotation))
    return tuple(items)


def _nullable_response_drift(
    spec: dict[str, Any],
    schema: dict[str, Any],
    annotations: tuple[Any, ...],
    *,
    path: str = "response",
) -> set[str]:
    resolved = _schema(spec, schema)
    alternatives = resolved.get("anyOf") or resolved.get("oneOf")
    if alternatives is not None:
        return {
            drift
            for alternative in alternatives
            if alternative.get("type") != "null"
            for drift in _nullable_response_drift(
                spec,
                alternative,
                annotations,
                path=path,
            )
        }
    if resolved.get("type") == "array":
        return _nullable_response_drift(
            spec,
            resolved["items"],
            _array_item_annotations(annotations),
            path=f"{path}[]",
        )

    fields_by_alias: dict[str, list[Any]] = {}
    for model in _model_types(annotations):
        for name, field in model.model_fields.items():
            fields_by_alias.setdefault(field.alias or name, []).append(field)

    drift: set[str] = set()
    for name, field_schema in resolved.get("properties", {}).items():
        fields = fields_by_alias.get(name, [])
        field_path = f"{path}.{name}"
        if _is_nullable(spec, field_schema) and not fields:
            drift.add(field_path)
        if fields:
            drift.update(
                _nullable_response_drift(
                    spec,
                    field_schema,
                    tuple(field.annotation for field in fields),
                    path=field_path,
                )
            )
    return drift


def audit_contract(spec: dict[str, Any]) -> ContractAudit:
    """Compare the checked-in contract with the hand-written operation registry."""
    failures: list[str] = []
    warnings: list[str] = []
    contract_ops = _operations(spec)

    new_operations = sorted(set(contract_ops) - KNOWN_OPERATION_IDS)
    warnings.extend(
        f"new operation is not classified: {operation_id}" for operation_id in new_operations
    )

    for registered in ops.OP_REGISTRY.values():
        operation = contract_ops.get(registered.operation_id)
        if operation is None:
            failures.append(f"operation removed or renamed: {registered.operation_id}")
            continue

        label = registered.operation_id
        if (operation["method"], operation["path"]) != (
            registered.method,
            registered.path_template,
        ):
            failures.append(f"{label}: method or path changed")

        supplied = {
            (location, name.lower() if location == "header" else name)
            for location, name in registered.supplied_parameters
        }
        parameters_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for parameter in operation["path_parameters"]:
            resolved = _schema(spec, parameter)
            parameters_by_key[_parameter_key(resolved)] = resolved
        for parameter in operation.get("parameters", []):
            resolved = _schema(spec, parameter)
            parameters_by_key[_parameter_key(resolved)] = resolved
        parameters = parameters_by_key.values()
        required_parameters = {
            _parameter_key(parameter)
            for parameter in parameters
            if parameter.get("required", False)
        }
        optional_parameters = {
            _parameter_key(parameter)
            for parameter in parameters
            if not parameter.get("required", False)
        }
        for parameter in sorted(required_parameters - supplied):
            failures.append(f"{label}: required parameter is not supplied: {parameter}")
        for parameter in sorted(optional_parameters - supplied):
            warnings.append(f"{label}: optional parameter is not adopted: {parameter}")

        request_body = operation.get("requestBody")
        if request_body is not None:
            model = registered.request_model
            if request_body.get("required", False) and model is None:
                failures.append(f"{label}: required request body is not supplied")
            elif model is not None:
                body_content = request_body["content"]
                media_type = (
                    "application/json"
                    if "application/json" in body_content
                    else "application/x-www-form-urlencoded"
                )
                body_schema = _schema(spec, body_content[media_type]["schema"])
                required_fields = set(body_schema.get("required", []))
                optional_fields = set(body_schema.get("properties", [])) - required_fields
                supplied_fields = {
                    field.alias or name for name, field in model.model_fields.items()
                }
                for field in sorted(required_fields - supplied_fields):
                    failures.append(f"{label}: required body field is not supplied: {field}")
                for field in sorted(optional_fields - supplied_fields):
                    warnings.append(f"{label}: optional body field is not adopted: {field}")

        if registered.response_models:
            nullable_drift: set[str] = set()
            for status in registered.success_statuses:
                response = operation["responses"].get(str(status), {})
                response_schema = (
                    response.get("content", {}).get("application/json", {}).get("schema")
                )
                if response_schema is None:
                    continue
                nullable_drift.update(
                    _nullable_response_drift(
                        spec,
                        response_schema,
                        registered.response_models,
                    )
                )
            for field in sorted(nullable_drift):
                warnings.append(f"{label}: nullable response field is not adopted: {field}")

        declared_statuses = {
            int(status) for status in operation["responses"] if status != "default"
        }
        handled_statuses = set(registered.success_statuses) | set(registered.error_statuses)
        for status in sorted(handled_statuses - declared_statuses):
            failures.append(f"{label}: handled status is no longer declared: {status}")
        for status in sorted(declared_statuses - handled_statuses):
            warnings.append(f"{label}: declared status is not handled: {status}")

    data_operation_id = ops.QUERY_RESOURCE_DATA.operation_id
    data_operation = contract_ops.get(data_operation_id)
    if data_operation is None:
        failures.append(f"{data_operation_id}: /data operation is unavailable for media-type audit")
    else:
        data_response = data_operation.get("responses", {}).get("200")
        data_content = data_response.get("content") if data_response is not None else None
        if data_content is None:
            failures.append(f"{data_operation_id}: /data 200 response content is missing")
        else:
            for media_type in sorted(DATA_MEDIA_TYPES - set(data_content)):
                failures.append(f"{data_operation_id}: missing media type: {media_type}")

    return ContractAudit(tuple(failures), tuple(warnings))


def _contract() -> dict[str, Any]:
    return json.loads((SDK_ROOT / "openapi.json").read_text())


def enforce_contract(audit: ContractAudit) -> None:
    """Fail on wrong-making drift and report additive drift as warnings."""
    assert not audit.failures, "\n".join(audit.failures)
    for message in audit.warnings:
        warnings.warn(message, AdditiveContractDriftWarning, stacklevel=2)


def test_checked_in_contract_has_no_wrong_making_drift() -> None:
    enforce_contract(audit_contract(_contract()))


def test_wrong_making_drift_fails() -> None:
    contract = _contract()
    operation = contract["paths"][ops.QUERY_RESOURCE_DATA.path_template]["get"]
    del operation["responses"]["200"]["content"]["application/parquet"]
    contract["paths"][ops.QUERY_RESOURCE_DATA.path_template]["parameters"] = [
        {
            "name": "required_filter",
            "in": "query",
            "required": True,
            "schema": {"type": "string"},
        }
    ]
    operation["responses"].pop("404")
    request_schema = contract["components"]["schemas"]["RegisterResourcesRequest"]
    request_schema["properties"]["required_context"] = {"type": "string"}
    request_schema["required"] = ["required_context"]
    del contract["paths"][ops.GET_BOOK.path_template]

    audit = audit_contract(contract)
    assert any("removed or renamed" in failure for failure in audit.failures)
    assert any("required parameter" in failure for failure in audit.failures)
    assert any("required body field" in failure for failure in audit.failures)
    assert any("handled status" in failure for failure in audit.failures)
    assert any("missing media type" in failure for failure in audit.failures)


def test_missing_data_response_content_fails_readably() -> None:
    contract = _contract()
    operation = contract["paths"][ops.QUERY_RESOURCE_DATA.path_template]["get"]
    del operation["responses"]["200"]["content"]

    audit = audit_contract(contract)

    assert any("/data 200 response content is missing" in failure for failure in audit.failures)

    contract_without_data = _contract()
    del contract_without_data["paths"][ops.QUERY_RESOURCE_DATA.path_template]
    audit_without_data = audit_contract(contract_without_data)
    assert any(
        "/data operation is unavailable" in failure for failure in audit_without_data.failures
    )


def test_additive_drift_warns() -> None:
    contract = _contract()
    operation = contract["paths"][ops.GET_BOOK.path_template]["get"]
    operation["parameters"].append(
        {"name": "locale", "in": "query", "required": False, "schema": {"type": "string"}}
    )
    operation["responses"]["206"] = {"description": "Partial response"}
    book_response = contract["components"]["schemas"]["BookResponse"]
    book_response["properties"]["future_note"] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    book_list_item = contract["components"]["schemas"]["BookListItem"]
    book_list_item["properties"]["future_nested"] = {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }
    contract["components"]["schemas"]["NullableFuture"] = {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }
    book_list_item["properties"]["future_ref"] = {"$ref": "#/components/schemas/NullableFuture"}
    contract["paths"]["/v1/new-operation"] = {
        "get": {"operationId": "newOperation", "responses": {"200": {"description": "OK"}}}
    }

    audit = audit_contract(contract)
    assert not audit.failures
    assert any("optional parameter" in warning for warning in audit.warnings)
    assert any("declared status" in warning for warning in audit.warnings)
    assert any("new operation" in warning for warning in audit.warnings)
    assert any("nullable response field" in warning for warning in audit.warnings)
    assert any("response.items[].future_nested" in warning for warning in audit.warnings)
    assert any("response.items[].future_ref" in warning for warning in audit.warnings)
    with pytest.warns(AdditiveContractDriftWarning) as caught:
        enforce_contract(audit)
    caught_messages = [str(item.message) for item in caught]
    injected_warning_substrings = (
        "new operation is not classified: newOperation",
        "optional parameter is not adopted: ('query', 'locale')",
        "declared status is not handled: 206",
        "response.future_note",
        "response.items[].future_nested",
        "response.items[].future_ref",
    )
    assert all(
        any(substring in message for message in caught_messages)
        for substring in injected_warning_substrings
    )
    assert len(caught) >= 6
