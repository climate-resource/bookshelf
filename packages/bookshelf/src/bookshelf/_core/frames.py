"""Bytes-to-DataFrame conversion for ``/data`` payloads.

Lives in the parse layer because generators cannot reach binary content negotiation.
pandas is imported on first use, so the CLI starts without loading it.
"""

import importlib
import io
import json
from typing import TYPE_CHECKING, Any

from bookshelf._core.errors import BookshelfError
from bookshelf._core.types import DataPayload, NotModified

if TYPE_CHECKING:
    import pandas as pd


class DataFrameSupportError(BookshelfError):
    """Raised when a conversion needs an optional package that is not installed."""


def require_package(module: str, caller: str) -> Any:
    """Import an optional package, reporting a missing one as a typed error.

    ``caller`` names what the user was trying to do, so the message points at their call
    rather than at the import.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        package = module.partition(".")[0]
        raise DataFrameSupportError(f"{caller} requires {package}: pip install {package}") from exc


def require_payload(result: DataPayload | NotModified) -> DataPayload:
    """Narrow a ``/data`` outcome to a payload for unconditional fetches."""
    if isinstance(result, NotModified):
        raise BookshelfError("expected a /data payload but the server answered 304 Not Modified")
    return result


def to_pandas(payload: DataPayload) -> "pd.DataFrame":
    """Convert a ``/data`` payload to a pandas DataFrame, dispatching on the negotiated format."""
    import pandas as pd

    if payload.format == "json":
        return pd.DataFrame(json.loads(payload.content))
    if payload.format == "csv":
        return pd.read_csv(io.BytesIO(payload.content))
    return pd.read_parquet(io.BytesIO(payload.content))
