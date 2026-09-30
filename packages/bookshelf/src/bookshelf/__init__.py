"""Public facade for the Bookshelf SDK."""

import importlib.metadata

from bookshelf._core.actions_oidc import ActionsTokenError
from bookshelf._core.config import PRODUCTION_API_URL, STAGING_API_URL
from bookshelf._core.errors import (
    APIError,
    AuthConfigurationError,
    AuthenticationError,
    AuthenticationRequiredError,
    BookshelfError,
    ConflictError,
    EntryNotFoundError,
    ForbiddenError,
    NotFoundError,
    OAuthProtocolError,
    SelectionError,
    ServerError,
    TransportError,
    UnexpectedResponseError,
    ValidationError,
)
from bookshelf._core.frames import DataFrameSupportError
from bookshelf._core.oauth import OAuthError
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
    DraftBook,
    HashMismatchError,
    PartialRegistrationError,
    RegisterItem,
    RegistrationFailure,
    RegistrationSuccess,
    Resource,
    UnsupportedConversionError,
    Used,
    Volume,
)
from bookshelf.publisher import (
    InvalidBundleError,
    replay_bundle,
    replay_bundle_sync,
    run_record,
    setup,
)

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
    "ActionsTokenError",
    "Activity",
    "AsyncActivity",
    "AsyncBook",
    "AsyncBookEntry",
    "AsyncBookshelf",
    "AsyncDraftBook",
    "AsyncResource",
    "AsyncVolume",
    "AuthConfigurationError",
    "AuthenticationError",
    "AuthenticationRequiredError",
    "Book",
    "BookEntry",
    "Bookshelf",
    "BookshelfError",
    "ConflictError",
    "ContentCache",
    "DataFrameSupportError",
    "DraftBook",
    "EntryNotFoundError",
    "ForbiddenError",
    "HashMismatchError",
    "InvalidBundleError",
    "NotFoundError",
    "OAuthError",
    "OAuthProtocolError",
    "PartialRegistrationError",
    "RegisterItem",
    "RegistrationFailure",
    "RegistrationSuccess",
    "Resource",
    "SelectionError",
    "ServerError",
    "TransportError",
    "UnexpectedResponseError",
    "UnsupportedConversionError",
    "Used",
    "ValidationError",
    "Volume",
    "__version__",
    "models",
    "replay_bundle",
    "replay_bundle_sync",
    "run_record",
    "setup",
    "uuid7",
]
