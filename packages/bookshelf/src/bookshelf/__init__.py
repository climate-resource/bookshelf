"""The Bookshelf SDK."""

import importlib.metadata

from bookshelf._core.actions_oidc import ActionsTokenError
from bookshelf._core.config import PRODUCTION_API_URL
from bookshelf._core.errors import (
    APIError,
    AuthConfigurationError,
    AuthenticationError,
    AuthenticationRequiredError,
    BookshelfError,
    ConfigurationError,
    ConflictError,
    ContractError,
    EntryNotFoundError,
    ForbiddenError,
    GatewayError,
    NotFoundError,
    RateLimitError,
    RequestValidationError,
    SelectionError,
    ServerError,
    TransportError,
    UnexpectedResponseError,
    VersionNotFoundError,
)
from bookshelf._core.frames import DataFrameSupportError
from bookshelf._core.oauth import OAuthError
from bookshelf._facade import (
    Activity,
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
    UnsupportedConversionError,
    Used,
    Volume,
)
from bookshelf._generated import OPENAPI_VERSION
from bookshelf._generated import models as models
from bookshelf._records import (
    BookCorrection,
    Facet,
    Facets,
    FacetValue,
    Identity,
    ItemError,
    Problem,
    ResourceType,
    SeriesMetadata,
    Visibility,
    VolumeSearchResults,
    VolumeSummary,
)
from bookshelf.cache import CacheDirectoryError, CacheSummary, ContentCache
from bookshelf.publisher import (
    InvalidBundleError,
    InvalidRecipeError,
    InvalidReferenceError,
    RecordingError,
    RecordRefusedError,
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
    "APIError",
    "ActionsTokenError",
    "Activity",
    "AuthConfigurationError",
    "AuthenticationError",
    "AuthenticationRequiredError",
    "Book",
    "BookCorrection",
    "BookEntry",
    "Bookshelf",
    "BookshelfError",
    "CacheDirectoryError",
    "CacheSummary",
    "ConfigurationError",
    "ConflictError",
    "ContentCache",
    "ContractError",
    "DataFrameSupportError",
    "DataPreview",
    "DraftBook",
    "EntryNotFoundError",
    "Facet",
    "FacetValue",
    "Facets",
    "ForbiddenError",
    "GatewayError",
    "HashMismatchError",
    "Identity",
    "InvalidBundleError",
    "InvalidRecipeError",
    "InvalidReferenceError",
    "ItemError",
    "NotFoundError",
    "OAuthError",
    "PartialRegistrationError",
    "Problem",
    "RateLimitError",
    "RecordRefusedError",
    "RecordingError",
    "RegisterItem",
    "RegistrationFailure",
    "RegistrationSuccess",
    "RequestValidationError",
    "Resource",
    "ResourceInfo",
    "ResourceType",
    "SelectionError",
    "SeriesMetadata",
    "ServerError",
    "TransportError",
    "UnexpectedResponseError",
    "UnsupportedConversionError",
    "Used",
    "VersionNotFoundError",
    "Visibility",
    "Volume",
    "VolumeSearchResults",
    "VolumeSummary",
    "__version__",
    "setup",
]
