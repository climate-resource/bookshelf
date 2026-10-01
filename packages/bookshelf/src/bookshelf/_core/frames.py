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
    import pyarrow.parquet as pq


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
    ``dictionary`` names text columns to read as categoricals, which hold each value once.
    """

    columns: list[str] | None = None
    rows: "pc.Expression | None" = None
    dictionary: list[str] | None = None


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
            frame = pd.read_parquet(
                path, columns=plan.columns, filters=plan.rows, read_dictionary=plan.dictionary
            )
            return frame if plan.rows is None else _widen_dropped_nulls(frame, pq.ParquetFile(path))
        # Only an empty field is missing, as on the platform, so a code like "NA" stays text.
        return pd.read_csv(
            path,
            compression="gzip" if magic[:2] == b"\x1f\x8b" else None,
            keep_default_na=False,
            na_values=[""],
        )
    except (ValueError, OSError, EOFError, zlib.error) as exc:
        raise BookshelfError(f"cannot read the stored resource as a frame: {exc}") from exc


def _widen_dropped_nulls(frame: "pd.DataFrame", parquet: "pq.ParquetFile") -> "pd.DataFrame":
    """Give back the dtypes a whole read picks for integer and bool columns holding nulls.

    pandas reads such a column as float or object, so filtering out its nulls would narrow it.
    """
    import numpy as np

    narrow = {
        column: dtype.kind
        for column, dtype in frame.dtypes.items()
        if isinstance(dtype, np.dtype) and dtype.kind in "iub"
    }
    widened = {
        column: "float64" if kind in "iu" else object
        for column, kind in narrow.items()
        if _holds_nulls(parquet, str(column))
    }
    return frame.astype(widened) if widened else frame


def _holds_nulls(parquet: "pq.ParquetFile", column: str) -> bool:
    """Whether a top-level column holds a null, from the statistics where the file has them."""
    metadata = parquet.metadata
    leaves = [i for i in range(metadata.num_columns) if metadata.schema.column(i).path == column]
    if len(leaves) != 1:
        return False
    for group in range(metadata.num_row_groups):
        statistics = metadata.row_group(group).column(leaves[0]).statistics
        if statistics is not None and statistics.has_null_count:
            nulls = statistics.null_count
        else:
            nulls = parquet.read_row_group(group, columns=[column]).column(0).null_count
        if nulls:
            return True
    return False


def to_pandas(payload: DataPayload) -> "pd.DataFrame":
    """Convert a ``/data`` payload to a pandas DataFrame, dispatching on the negotiated format."""
    import pandas as pd

    if payload.format == "json":
        return pd.DataFrame(json.loads(payload.content))
    if payload.format == "csv":
        return pd.read_csv(io.BytesIO(payload.content))
    return pd.read_parquet(io.BytesIO(payload.content))
