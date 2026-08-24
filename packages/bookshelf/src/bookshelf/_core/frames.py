"""Bytes-to-DataFrame conversion for ``/data`` payloads.

Lives in the parse layer because generators cannot reach binary content negotiation.
pandas and pyarrow are optional (``bookshelf[dataframes]``), so imports are deferred.
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
    """Raised when frame conversion is requested without the ``dataframes`` extra installed."""


def require_extra(module: str, caller: str) -> Any:
    """Import a module from the ``dataframes`` extra, reporting a missing one as a typed error.

    ``caller`` names what the user was trying to do, so the message points at their call
    rather than at the import.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise DataFrameSupportError(
            f"{caller} requires the 'dataframes' extra: pip install 'bookshelf[dataframes]'"
        ) from exc


def require_payload(result: DataPayload | NotModified) -> DataPayload:
    """Narrow a ``/data`` outcome to a payload for unconditional fetches."""
    if isinstance(result, NotModified):
        raise BookshelfError("expected a /data payload but the server answered 304 Not Modified")
    return result


def to_pandas(payload: DataPayload) -> "pd.DataFrame":
    """Convert a ``/data`` payload to a pandas DataFrame, dispatching on the negotiated format."""
    pandas = require_extra("pandas", "DataFrame conversion")
    if payload.format == "json":
        rows = json.loads(payload.content)
        frame: pd.DataFrame = pandas.DataFrame(rows)
        return frame
    if payload.format == "csv":
        return pandas.read_csv(io.BytesIO(payload.content))  # type: ignore[no-any-return]
    return pandas.read_parquet(io.BytesIO(payload.content))  # type: ignore[no-any-return]
