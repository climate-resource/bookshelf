"""Public facade for the Bookshelf SDK."""

import importlib.metadata

from bookshelf._core.config import PRODUCTION_API_URL, STAGING_API_URL
from bookshelf._core.errors import (
    APIError,
    AuthenticationError,
    AuthenticationRequiredError,
    BookshelfError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServerError,
    TransportError,
    UnexpectedResponseError,
)
from bookshelf._core.frames import DataFrameSupportError
from bookshelf._generated import OPENAPI_VERSION, models
from bookshelf._produce.helpers import uuid7
from bookshelf.cache import ContentCache
from bookshelf.facade import (
    Activity,
    AsyncActivity,
    AsyncBook,
    AsyncBookEntry,
    AsyncBookshelf,
    AsyncDraftBook,
    AsyncResource,
    AsyncVolume,
    Book,
    BookEntry,
    Bookshelf,
    DataPreview,
    DraftBook,
    HashMismatchError,
    PartialRegistrationError,
    RegisterItem,
    RegistrationFailure,
    RegistrationSuccess,
    Resource,
    ResourceInfo,
    SelectionError,
    UnsupportedConversionError,
    Used,
    Volume,
)
from bookshelf.publisher import replay_bundle, replay_bundle_sync, run_record, setup

__version__ = importlib.metadata.version("bookshelf")

_LEGACY_NAMES = frozenset({"BookShelf", "LocalBook"})


def __getattr__(name: str) -> object:
    """Serve the 0.4 ``BookShelf`` and ``LocalBook`` with a warning instead of an AttributeError."""
    if name in _LEGACY_NAMES:
        from bookshelf import legacy

        legacy._deprecated(f"bookshelf.{name}", "bookshelf.Bookshelf")
        return getattr(legacy, name)
    raise AttributeError(f"module 'bookshelf' has no attribute {name!r}")


__all__ = [
    "OPENAPI_VERSION",
    "PRODUCTION_API_URL",
    "STAGING_API_URL",
    "APIError",
    "Activity",
    "AsyncActivity",
    "AsyncBook",
    "AsyncBookEntry",
    "AsyncBookshelf",
    "AsyncDraftBook",
    "AsyncResource",
    "AsyncVolume",
    "AuthenticationError",
    "AuthenticationRequiredError",
    "Book",
    "BookEntry",
    "Bookshelf",
    "BookshelfError",
    "ConflictError",
    "ContentCache",
    "DataFrameSupportError",
    "DataPreview",
    "DraftBook",
    "ForbiddenError",
    "HashMismatchError",
    "NotFoundError",
    "PartialRegistrationError",
    "RegisterItem",
    "RegistrationFailure",
    "RegistrationSuccess",
    "Resource",
    "ResourceInfo",
    "SelectionError",
    "ServerError",
    "TransportError",
    "UnexpectedResponseError",
    "UnsupportedConversionError",
    "Used",
    "Volume",
    "__version__",
    "models",
    "replay_bundle",
    "replay_bundle_sync",
    "run_record",
    "setup",
    "uuid7",
]
