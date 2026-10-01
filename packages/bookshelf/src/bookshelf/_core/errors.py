"""Typed exception hierarchy mapped from RFC 7807 ``problem+json`` responses.

The parse layer is the only place that raises these from wire bytes,
so both client surfaces fail identically.
"""

import json
from http import HTTPStatus
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from bookshelf._core.retry import RATE_LIMITED, parse_retry_after
from bookshelf._core.types import ApiResponse
from bookshelf._generated import models

PROBLEM_MEDIA_TYPE = "application/problem+json"


class BookshelfError(Exception):
    """Base exception for all Bookshelf SDK errors."""


class TransportError(BookshelfError):
    """A network-level failure with no HTTP response (after transient retries)."""


class ConfigurationError(BookshelfError):
    """A setting such as the API URL is malformed."""


class AuthConfigurationError(BookshelfError):
    """Ambient credential configuration is inconsistent or incomplete."""


class AuthenticationRequiredError(BookshelfError):
    """No credential the API accepts is available, and none can be obtained here."""


class _UnquotedKeyError(KeyError):
    # KeyError would otherwise print its message as a quoted repr.
    def __str__(self) -> str:
        return Exception.__str__(self)


class SelectionError(BookshelfError, _UnquotedKeyError):
    """A selection names a column the data does not have, or a value a column cannot hold."""


class APIError(BookshelfError):
    """An HTTP error response from the API.

    Attributes:
        status_code: HTTP status code returned by the server.
        detail: Human-readable detail string.
        problem: The parsed RFC 7807 document, when one was returned.
        request_method: HTTP method of the failing request, when known.
        request_url: URL or path of the failing request, when known.
    """

    def __init__(
        self,
        detail: str,
        *,
        status_code: int,
        problem: models.Problem | None = None,
        request_method: str | None = None,
        request_url: str | None = None,
    ) -> None:
        location = f" [{request_method} {request_url}]" if request_method and request_url else ""
        super().__init__(f"{detail}{location}")
        self.detail = detail
        self.status_code = status_code
        self.problem = problem
        self.request_method = request_method
        self.request_url = request_url

    @property
    def errors(self) -> list[dict[str, Any]]:
        """Raw error details from the problem document."""
        if self.problem is None or self.problem.errors is None:
            return []
        return self.problem.errors

    @property
    def item_errors(self) -> list[models.ItemError]:
        """Typed per-item failures from a non-atomic batch, per the 409 + ``ItemError`` contract.

        Entries that do not match the ``ItemError`` shape are omitted.
        The raw documents stay available on :attr:`errors`.
        """
        typed: list[models.ItemError] = []
        for entry in self.errors:
            try:
                typed.append(models.ItemError.model_validate(entry))
            except PydanticValidationError:
                continue
        return typed


class AuthenticationError(APIError):
    """Raised on HTTP 401 responses."""


class ForbiddenError(APIError):
    """Raised on HTTP 403 responses."""


class NotFoundError(APIError, LookupError):
    """The named volume, version, book, entry or resource does not exist.

    Raised on HTTP 404 responses,
    and with ``status_code`` 404 when a lookup the SDK settles locally finds nothing.
    """


class EntryNotFoundError(NotFoundError, _UnquotedKeyError):
    """A book indexes no entry by the requested name."""


class ConflictError(APIError):
    """Raised on HTTP 409 responses."""


class RequestValidationError(APIError):
    """Raised on HTTP 400 / 422 request-validation failures."""


class ServerError(APIError):
    """Raised on HTTP 5xx responses (after transient retries)."""


class RateLimitError(APIError):
    """Raised on HTTP 429 responses (after waiting out the retries the server allowed).

    Attributes:
        retry_after: Seconds the server asked the client to wait, when it said.
    """

    def __init__(
        self,
        detail: str,
        *,
        status_code: int = RATE_LIMITED,
        retry_after: float | None = None,
        problem: models.Problem | None = None,
        request_method: str | None = None,
        request_url: str | None = None,
    ) -> None:
        super().__init__(
            detail,
            status_code=status_code,
            problem=problem,
            request_method=request_method,
            request_url=request_url,
        )
        self.retry_after = retry_after


class GatewayError(APIError):
    """A proxy or CDN in front of the API refused the request with a non-JSON error page.

    The request may never have reached the API, so the status says nothing about the data.
    """


class OAuthProtocolError(APIError):
    """An OAuth ``{"error": ...}`` body from the agent authorization server.

    ``error`` carries the OAuth error code (e.g. ``authorization_pending``),
    which token-endpoint polling dispatches on.
    """

    def __init__(
        self,
        detail: str,
        *,
        error: str,
        status_code: int,
        request_method: str | None = None,
        request_url: str | None = None,
    ) -> None:
        super().__init__(
            detail,
            status_code=status_code,
            request_method=request_method,
            request_url=request_url,
        )
        self.error = error


class UnexpectedResponseError(APIError):
    """Raised when the server answers with a status the contract does not declare."""


_ERROR_BY_STATUS: dict[int, type[APIError]] = {
    400: RequestValidationError,
    401: AuthenticationError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    422: RequestValidationError,
}


def _parse_problem(response: ApiResponse) -> models.Problem | None:
    if response.media_type != PROBLEM_MEDIA_TYPE:
        return None
    try:
        return models.Problem.model_validate_json(response.content)
    except ValueError:
        return None


_NOT_JSON = object()


def _json_body(response: ApiResponse) -> Any:
    if response.media_type == "text/html":
        return _NOT_JSON
    try:
        return json.loads(response.content)
    except ValueError:
        return _NOT_JSON


def _non_json_detail(response: ApiResponse) -> str:
    """Describe a body that is not JSON by its status and type, since it is usually a proxy page."""
    try:
        status = f"HTTP {response.status_code} {HTTPStatus(response.status_code).phrase}"
    except ValueError:
        status = f"HTTP {response.status_code}"
    if not response.content:
        return f"{status} with an empty body"
    return f"{status} with a {response.media_type or 'untyped'} body"


def _json_detail(body: Any) -> str:
    """Best-effort detail for JSON bodies that are not problem documents (e.g. FastAPI's own 422)."""
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            return _describe_field_errors(detail) or json.dumps(detail)[:200]
        if detail is not None:
            return json.dumps(detail)[:200]
    return json.dumps(body)[:200]


def _describe_field_errors(field_errors: list[Any]) -> str:
    described = []
    for error in field_errors:
        if isinstance(error, dict) and "msg" in error:
            location = ".".join(str(part) for part in error.get("loc") or ())
            described.append(f"{location}: {error['msg']}" if location else str(error["msg"]))
        else:
            described.append(json.dumps(error))
    return ", ".join(described)


def error_from_response(
    response: ApiResponse,
    *,
    declared: bool,
    request_method: str | None = None,
    request_url: str | None = None,
) -> APIError:
    """Map an error :class:`ApiResponse` to the typed exception hierarchy.

    ``declared`` is whether the op's contract lists this status.
    An undeclared status maps to :class:`UnexpectedResponseError`
    so contract drift surfaces loudly instead of masquerading as a domain error.
    A body that is not JSON came from something in front of the API,
    so its status maps without consulting the contract, and the body itself is never quoted.
    """
    status_code = response.status_code
    problem = _parse_problem(response)
    body = None if problem is not None else _json_body(response)
    is_json = body is not _NOT_JSON
    if problem is not None:
        detail = problem.detail
    elif is_json:
        detail = _json_detail(body)
    else:
        detail = _non_json_detail(response)
    request_url = response.url or request_url
    if status_code == RATE_LIMITED:
        return RateLimitError(
            detail,
            retry_after=parse_retry_after(response.headers.get("retry-after")),
            problem=problem,
            request_method=request_method,
            request_url=request_url,
        )
    if status_code >= 500:
        exc_type: type[APIError] = ServerError
    elif not is_json:
        exc_type = AuthenticationError if status_code == 401 else GatewayError
    elif declared and status_code in _ERROR_BY_STATUS:
        exc_type = _ERROR_BY_STATUS[status_code]
    else:
        exc_type = UnexpectedResponseError
    if exc_type is RequestValidationError and problem is not None and problem.errors:
        detail = f"{detail}: {_describe_field_errors(problem.errors)}"
    return exc_type(
        detail,
        status_code=status_code,
        problem=problem,
        request_method=request_method,
        request_url=request_url,
    )
