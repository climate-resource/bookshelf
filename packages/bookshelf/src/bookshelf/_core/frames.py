"""Bytes-to-DataFrame conversion for ``/data`` payloads.

Lives in the parse layer because generators cannot reach binary content negotiation.
pandas and pyarrow are optional (``bookshelf[dataframes]``), so imports are deferred.
"""

import io
import json
from typing import TYPE_CHECKING, Any

from bookshelf._core.errors import BookshelfError
from bookshelf._core.types import DataPayload, NotModified

if TYPE_CHECKING:
    import pandas as pd


class DataFrameSupportError(BookshelfError):
    """Raised when frame conversion is requested without the ``dataframes`` extra installed."""


def _pandas() -> Any:
    try:
        import pandas
    except ImportError as exc:  # pragma: no cover
        raise DataFrameSupportError(
            "DataFrame conversion requires the 'dataframes' extra: "
            "pip install 'bookshelf[dataframes]'"
        ) from exc
    return pandas


def require_payload(result: DataPayload | NotModified) -> DataPayload:
    """Narrow a ``/data`` outcome to a payload for unconditional fetches."""
    if isinstance(result, NotModified):
        raise BookshelfError("expected a /data payload but the server answered 304 Not Modified")
    return result


def to_pandas(payload: DataPayload) -> "pd.DataFrame":
    """Convert a ``/data`` payload to a pandas DataFrame, dispatching on the negotiated format."""
    pandas = _pandas()
    if payload.format == "json":
        rows = json.loads(payload.content)
        frame: pd.DataFrame = pandas.DataFrame(rows)
        return frame
    if payload.format == "csv":
        return pandas.read_csv(io.BytesIO(payload.content))  # type: ignore[no-any-return]
    return pandas.read_parquet(io.BytesIO(payload.content))  # type: ignore[no-any-return]
