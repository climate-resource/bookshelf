"""Bytes-to-DataFrame conversion for ``/data`` payloads.

Lives in the parse layer because generators cannot reach binary content negotiation.
pandas is imported on first use, so the CLI starts without loading it.
"""

import importlib
import io
import json
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from bookshelf._core.errors import BookshelfError
from bookshelf._core.types import DataPayload, NotModified

if TYPE_CHECKING:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.compute as pc


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
        raise DataFrameSupportError(f"{caller} requires {module}: pip install {module}") from exc


def require_payload(result: DataPayload | NotModified) -> DataPayload:
    """Narrow a ``/data`` outcome to a payload for unconditional fetches."""
    if isinstance(result, NotModified):
        raise BookshelfError("expected a /data payload but the server answered 304 Not Modified")
    return result


class ParquetScan(NamedTuple):
    """The columns and rows to read from a parquet file, ``None`` meaning all of them.

    A scan may keep more than the selection needs, but never less.
    """

    columns: list[str] | None = None
    rows: "pc.Expression | None" = None


def read_frame(
    path: Path, *, scan: "Callable[[pa.Schema], ParquetScan] | None" = None
) -> "pd.DataFrame":
    """Read a stored resource, which the platform only holds as parquet or csv.

    ``scan`` plans a parquet read from the file's schema,
    so pyarrow skips unread columns and filters rows before they reach pandas.
    Row groups whose statistics rule out the filter are not read at all.
    """
    import pandas as pd

    with path.open("rb") as stream:
        magic = stream.read(4)
    try:
        if magic == b"PAR1":
            import pyarrow.parquet as pq

            plan = ParquetScan() if scan is None else scan(pq.read_schema(path))
            return pd.read_parquet(path, columns=plan.columns, filters=plan.rows)
        # Only an empty field is missing, as on the platform, so a code like "NA" stays text.
        return pd.read_csv(
            path,
            compression="gzip" if magic[:2] == b"\x1f\x8b" else None,
            keep_default_na=False,
            na_values=[""],
        )
    except (ValueError, OSError, EOFError, zlib.error) as exc:
        raise BookshelfError(f"cannot read the stored resource as a frame: {exc}") from exc


def to_pandas(payload: DataPayload) -> "pd.DataFrame":
    """Convert a ``/data`` payload to a pandas DataFrame, dispatching on the negotiated format."""
    import pandas as pd

    if payload.format == "json":
        return pd.DataFrame(json.loads(payload.content))
    if payload.format == "csv":
        return pd.read_csv(io.BytesIO(payload.content))
    return pd.read_parquet(io.BytesIO(payload.content))
