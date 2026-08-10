"""Materialise an in-memory object into the bytes a registration uploads.

This is the one ``serialise -> hash`` step shared by the live write path
and the recording sink.
The bytes a bundle records therefore hash identically to the bytes replay uploads.
Callers must reuse :func:`serialise`
because a second implementation could drift and break byte parity.

Two shapes are produced from the resource ``type``:

- ``timeseries`` / ``tabular`` -> **parquet**.
  A polars or pandas ``DataFrame`` is encoded with pinned, deterministic
  writer options (see :func:`_dataframe_to_parquet`).
- ``document`` / ``binary`` / ``geospatial`` -> **raw bytes**,
  stored exactly as given (a ``.ipynb`` / ``.html`` / arbitrary blob).

Already-serialised ``bytes`` and ``Path`` inputs pass through unchanged.
An advanced caller can therefore supply pre-encoded parquet.

The Parquet writer uses pinned options.
The same frame therefore produces the same bytes within one environment.
pyarrow stamps its own library version into the file footer (``created_by``),
and the public writer API cannot suppress it.
Bytes are reproducible for a given pyarrow version.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from bookshelf._core.frames import require_extra
from bookshelf._core.hashing import sha256_hex

if TYPE_CHECKING:
    import pyarrow as pa

# Resource types whose in-memory frames are encoded to parquet.
_PARQUET_TYPES = frozenset({"timeseries", "tabular"})

_PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"
_OPAQUE_CONTENT_TYPE = "application/octet-stream"


class SerialisedObject(NamedTuple):
    """The bytes to upload plus their canonical hash, content type, and format.

    ``format`` is the declared storage format for registration.
    It is set when the serialiser encoded the bytes
    or when a ``Path`` suffix identifies the format.
    Raw ``bytes`` leave it as ``None``.
    """

    data: bytes
    hash: str
    content_type: str
    format: str | None = None


def serialise(obj: Any, *, type: str) -> SerialisedObject:
    """Materialise ``obj`` into ``(bytes, hash, content_type, format)`` for upload.

    ``obj`` is a polars or pandas ``DataFrame``,
    raw ``bytes``,
    or a :class:`~pathlib.Path`.
    For a parquet ``type`` such as ``timeseries`` or ``tabular``,
    a ``DataFrame`` is encoded to deterministic parquet.
    ``bytes`` and ``Path`` inputs pass through unchanged for every type.
    The hash is the canonical ``sha256:<hex>`` of the resulting bytes.
    """
    data, content_type, format = _materialise(obj, type=type)
    return SerialisedObject(
        data=data, hash=sha256_hex(data), content_type=content_type, format=format
    )


def _materialise(obj: Any, *, type: str) -> tuple[bytes, str, str | None]:
    """Return ``(bytes, content_type, format)`` for ``obj`` under resource ``type``."""
    if isinstance(obj, bytes):
        # Already serialised:
        # store verbatim regardless of type.
        # The format is unknowable from bytes alone,
        # so it is not claimed.
        return obj, _content_type_for(type), None
    if isinstance(obj, Path):
        return obj.read_bytes(), _content_type_for(type), _format_from_suffix(obj.name)
    if type in _PARQUET_TYPES:
        return _dataframe_to_parquet(obj), _PARQUET_CONTENT_TYPE, "parquet"
    raise TypeError(
        f"Cannot serialise {obj.__class__.__name__!r} for resource type {type!r}, "
        "pass bytes or a Path for opaque/document resources, "
        "or a polars/pandas DataFrame for timeseries/tabular resources."
    )


def _format_from_suffix(name: str) -> str | None:
    """Infer a declared storage format from a filename suffix, or None.

    Managed uploads land at content-addressed keys with no suffix.
    The source filename is therefore the only place the format survives.
    Only formats that the server's query engine can scan are claimed.
    Anything else stays None.
    """
    lowered = name.lower()
    if lowered.endswith((".parquet", ".pq")):
        return "parquet"
    if lowered.endswith((".csv.gz", ".csvgz")):
        return "csv.gz"
    if lowered.endswith(".csv"):
        return "csv"
    return None


def _content_type_for(type: str) -> str:
    """Content type for already-serialised bytes of resource ``type``."""
    return _PARQUET_CONTENT_TYPE if type in _PARQUET_TYPES else _OPAQUE_CONTENT_TYPE


def _dataframe_to_parquet(df: Any) -> bytes:
    """Encode a polars or pandas ``DataFrame`` to deterministic parquet bytes.

    The frame is first converted to a pyarrow ``Table``.
    Both polars and pandas round-trip through Arrow,
    so either yields the same table and bytes.
    The writer uses these pinned options:

    - ``compression="none"`` and ``write_statistics=False`` remove
      compression- and statistics-driven byte variance.
    - ``version`` and ``data_page_version`` select a stable format.
    - The pandas index and schema metadata are removed.
      A pandas frame therefore encodes identically to the equivalent polars frame.

    Requires the optional ``dataframes`` extra (``polars`` / ``pandas`` /
    ``pyarrow``).
    """
    pq = require_extra("pyarrow.parquet", "Serialising a DataFrame")

    table = _to_arrow_table(df)
    buf = io.BytesIO()
    pq.write_table(
        table,
        buf,
        compression="none",
        write_statistics=False,
        version="2.6",
        data_page_version="2.0",
    )
    return buf.getvalue()


def _to_arrow_table(df: Any) -> pa.Table:
    """Convert a polars or pandas ``DataFrame`` to a pyarrow ``Table``.

    pandas frames drop their index and have pandas-specific schema metadata
    stripped, so the byte output matches the equivalent polars frame.
    """
    import pyarrow as pa

    to_arrow = getattr(df, "to_arrow", None)
    if callable(to_arrow):
        # polars DataFrame.
        table = to_arrow()
        if isinstance(table, pa.Table):
            return table
    if _is_pandas_frame(df):
        table = pa.Table.from_pandas(df, preserve_index=False)
        return table.replace_schema_metadata(None)
    raise TypeError(f"Expected a polars or pandas DataFrame, got {type(df).__name__!r}.")


def _is_pandas_frame(obj: Any) -> bool:
    """Return whether ``obj`` is a pandas ``DataFrame`` without importing pandas eagerly."""
    try:
        import pandas as pd
    except ImportError:
        return False
    return isinstance(obj, pd.DataFrame)


__all__ = ["SerialisedObject", "serialise"]
