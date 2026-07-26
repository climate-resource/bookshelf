"""Transport core for the Bookshelf SDK.

Request building and response parsing are pure functions that never touch the network.
Each operation has a ``build_*`` function that produces an :class:`ApiRequest`
and a ``parse_*`` function that consumes an :class:`ApiResponse`.
:class:`BookshelfClient` is a thin shell that carries bytes between the two over httpx,
once per surface (sync and async), so the two surfaces cannot drift.

Keeping the request/response logic free of I/O means every operation
can be tested without a socket,
and cross-cutting concerns (errors, retry, dataframe decoding) live in one place.
"""

from bookshelf._core.client import BookshelfClient
from bookshelf._core.ops import OP_REGISTRY, OpSpec
from bookshelf._core.retry import RetryPolicy
from bookshelf._core.types import (
    ACCEPT_BY_FORMAT,
    ApiRequest,
    ApiResponse,
    DataFormat,
    DataPayload,
    NotModified,
)

__all__ = [
    "ACCEPT_BY_FORMAT",
    "OP_REGISTRY",
    "ApiRequest",
    "ApiResponse",
    "BookshelfClient",
    "DataFormat",
    "DataPayload",
    "NotModified",
    "OpSpec",
    "RetryPolicy",
]
