"""Typed exception hierarchy mapped from RFC 7807 ``problem+json`` responses.

The parse layer is the only place that raises these from wire bytes,
so both client surfaces fail identically.
"""

import json
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from bookshelf._core.types import ApiResponse
from bookshelf._generated import models

PROBLEM_MEDIA_TYPE = "application/problem+json"


class BookshelfError(Exception):
    """Base exception for all Bookshelf SDK errors."""


class TransportError(BookshelfError):
    """A network-level failure with no HTTP response (after transient retries)."""


class AuthConfigurationError(BookshelfError):
    """Ambient credential configuration is inconsistent or incomplete."""


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


class NotFoundError(APIError):
    """Raised on HTTP 404 responses."""


class ConflictError(APIError):
    """Raised on HTTP 409 responses."""


class ValidationError(APIError):
    """Raised on HTTP 400 / 422 request-validation failures."""


class ServerError(APIError):
    """Raised on HTTP 5xx responses (after transient retries)."""


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
    400: ValidationError,
    401: AuthenticationError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
}


def _parse_problem(response: ApiResponse) -> models.Problem | None:
    if response.media_type != PROBLEM_MEDIA_TYPE:
        return None
    try:
        return models.Problem.model_validate_json(response.content)
    except ValueError:
        return None


def _fallback_detail(response: ApiResponse) -> str:
    """Best-effort detail for non-problem error bodies (e.g. FastAPI 422 or a bare proxy 502)."""
    try:
        body = json.loads(response.content)
    except ValueError:
        return response.content.decode("utf-8", errors="replace")[:200] or "no response body"
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return json.dumps(detail)
    return json.dumps(body)[:200]


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
    """
    problem = _parse_problem(response)
    detail = problem.detail if problem is not None else _fallback_detail(response)
    if response.status_code >= 500:
        exc_type: type[APIError] = ServerError
    elif declared and response.status_code in _ERROR_BY_STATUS:
        exc_type = _ERROR_BY_STATUS[response.status_code]
    else:
        exc_type = UnexpectedResponseError
    return exc_type(
        detail,
        status_code=response.status_code,
        problem=problem,
        request_method=request_method,
        request_url=request_url,
    )
