"""Public facade for the Bookshelf SDK."""

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import OPENAPI_VERSION, models
from bookshelf.cache import ContentCache
from bookshelf.facade import (
    Activity,
    AsyncActivity,
    AsyncBook,
    AsyncBookEntry,
    AsyncBookshelf,
    AsyncDraftBook,
    AsyncResource,
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
)
from bookshelf.publisher import replay_bundle, replay_bundle_sync, run_record, setup

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
    "Activity",
    "AsyncActivity",
    "AsyncBook",
    "AsyncBookEntry",
    "AsyncBookshelf",
    "AsyncDraftBook",
    "AsyncResource",
    "Book",
    "BookEntry",
    "Bookshelf",
    "BookshelfError",
    "ContentCache",
    "DraftBook",
    "HashMismatchError",
    "PartialRegistrationError",
    "RegisterItem",
    "RegistrationFailure",
    "RegistrationSuccess",
    "Resource",
    "UnsupportedConversionError",
    "Used",
    "models",
    "replay_bundle",
    "replay_bundle_sync",
    "run_record",
    "setup",
]
