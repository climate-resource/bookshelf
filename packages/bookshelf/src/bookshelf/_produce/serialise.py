"""Materialise an in-memory object into the bytes a registration uploads.

This is the one ``serialise -> hash`` step shared by the live write path
and the recording sink.
The bytes a bundle records therefore hash identically to the bytes replay uploads.
Callers must reuse :func:`serialise`
because a second implementation could drift and break byte parity.

Three shapes are produced from the resource ``type``:

- ``timeseries`` / ``tabular`` -> **parquet**.
  A polars or pandas ``DataFrame`` is encoded with pinned, deterministic
  writer options (see :func:`_dataframe_to_parquet`).
- ``figure`` -> **png**.
  A matplotlib figure is saved as a png master (see :func:`_figure_to_png`).
- ``document`` / ``binary`` / ``geospatial`` -> **raw bytes**,
  stored exactly as given (a ``.ipynb`` / ``.html`` / arbitrary blob).

Already-serialised ``bytes`` and ``Path`` inputs pass through unchanged.
An advanced caller can therefore supply pre-encoded parquet.
A figure only accepts them when they are already a png.

A matplotlib figure also saves to a separate svg companion (see :func:`figure_svg`).
The recorder stores it beside the png master,
and the platform serves it as the figure's vector format.

The Parquet writer uses pinned options.
The same frame therefore produces the same bytes within one environment.
pyarrow stamps its own library version into the file footer (``created_by``),
and the public writer API cannot suppress it.
Bytes are reproducible for a given pyarrow version.
"""

from __future__ import annotations

import io
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from bookshelf._core.hashing import sha256_hex
from bookshelf._generated import models

if TYPE_CHECKING:
    import pyarrow as pa

# Resource types whose in-memory frames are encoded to parquet.
_PARQUET_TYPES = frozenset({"timeseries", "tabular"})

_PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"
_PNG_CONTENT_TYPE = "image/png"
SVG_CONTENT_TYPE = "image/svg+xml"
_OPAQUE_CONTENT_TYPE = "application/octet-stream"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The platform's largest raster size, so the master is never upscaled.
_MASTER_WIDTH_PX = 2400
_MIN_FIGURE_DPI = 200
# The platform refuses a larger svg companion, and the figure still publishes as a png.
MAX_FIGURE_SVG_BYTES = 20 * 1024 * 1024

logger = logging.getLogger(__name__)


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
    if type == models.ResourceType.figure:
        return _figure_png(obj), content_type_for(type), "png"
    if isinstance(obj, bytes):
        # Already serialised:
        # store verbatim regardless of type.
        # The format is unknowable from bytes alone,
        # so it is not claimed.
        return obj, content_type_for(type), None
    if isinstance(obj, Path):
        return obj.read_bytes(), content_type_for(type), format_from_suffix(obj.name)
    if type in _PARQUET_TYPES:
        return _dataframe_to_parquet(obj), _PARQUET_CONTENT_TYPE, "parquet"
    raise TypeError(
        f"Cannot serialise {obj.__class__.__name__!r} for resource type {type!r}, "
        "pass bytes or a Path for opaque/document resources, "
        "or a polars/pandas DataFrame for timeseries/tabular resources."
    )


def format_from_suffix(name: str) -> str | None:
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


def content_type_for(type: str) -> str:
    """Content type for already-serialised bytes of resource ``type``."""
    if type == models.ResourceType.figure:
        return _PNG_CONTENT_TYPE
    return _PARQUET_CONTENT_TYPE if type in _PARQUET_TYPES else _OPAQUE_CONTENT_TYPE


def _figure_png(obj: Any) -> bytes:
    """Return the png master for a matplotlib figure, or for bytes or a path already holding one."""
    if isinstance(obj, bytes | Path):
        data = obj if isinstance(obj, bytes) else obj.read_bytes()
        if not data.startswith(_PNG_SIGNATURE):
            raise ValueError("A figure must be a png, and these bytes are not one.")
        return data
    if _is_matplotlib_figure(obj):
        return _figure_to_png(obj)
    raise TypeError(
        f"Cannot serialise {obj.__class__.__name__!r} for resource type 'figure', "
        "pass a matplotlib figure, or png bytes or a Path to a png."
    )


def _is_matplotlib_figure(obj: Any) -> bool:
    """Duck typed, so matplotlib stays out of the import graph for everyone who does not plot."""
    return callable(getattr(obj, "savefig", None)) and callable(getattr(obj, "get_figwidth", None))


def figure_svg(obj: Any) -> bytes | None:
    """Save a matplotlib figure as a reproducible svg, or return ``None``.

    Only a matplotlib figure yields one.
    Bytes or a path already holding a png carry no vector to save, so they return ``None``.
    The date is dropped and the hash salt is fixed,
    so an unchanged figure saves to the same bytes on every rebuild.
    Text stays drawn as paths, matplotlib's default,
    so the svg looks the same without the producer's fonts.
    An svg over :data:`MAX_FIGURE_SVG_BYTES` returns ``None`` with a warning,
    because the platform refuses it and the figure still publishes as a png.
    """
    if not _is_matplotlib_figure(obj):
        return None
    # A figure object already proves matplotlib is installed.
    import matplotlib

    buffer = io.BytesIO()
    with matplotlib.rc_context({"svg.hashsalt": "bookshelf"}):
        obj.savefig(buffer, format="svg", metadata={"Date": None})
    data = buffer.getvalue()
    if len(data) > MAX_FIGURE_SVG_BYTES:
        logger.warning(
            "The svg of this figure is %d bytes, over the %d byte limit, "
            "so only the png master is recorded.",
            len(data),
            MAX_FIGURE_SVG_BYTES,
        )
        return None
    return data


def _figure_to_png(fig: Any) -> bytes:
    """Save a matplotlib figure as a reproducible png at least 2400 px wide.

    ``bbox_inches`` stays unset so the width is exactly the figure width times the dpi.
    Dropping ``Software`` keeps the matplotlib version out of the bytes.
    """
    dpi = max(_MIN_FIGURE_DPI, math.ceil(_MASTER_WIDTH_PX / fig.get_figwidth()))
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi, metadata={"Software": None})
    return buffer.getvalue()


def _dataframe_to_parquet(df: Any) -> bytes:
    """Encode a polars or pandas ``DataFrame`` to deterministic parquet bytes.

    The frame is first converted to a pyarrow ``Table``.
    Both polars and pandas round-trip through Arrow,
    so either yields the same table and bytes.
    The writer uses these pinned options:

    - ``compression="none"`` and ``write_statistics=False`` remove
      compression- and statistics-driven byte variance.
    - ``version`` and ``data_page_version`` select a stable format.
    - The pandas index is removed and the schema is made canonical (see :func:`_to_arrow_table`).
      A pandas frame therefore encodes identically to the equivalent polars frame.
    """
    import pyarrow.parquet as pq

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
    """Convert a polars or pandas ``DataFrame`` to a pyarrow ``Table`` with a canonical schema.

    pandas and polars choose different offset and index widths for the same data,
    and each attaches its own metadata.
    Every column is cast to the widths polars writes and all metadata is dropped,
    so either frame yields the same bytes.
    """
    import pyarrow as pa

    table = _frame_to_arrow(df)
    return table.cast(pa.schema([_canonical_field(field) for field in table.schema]))


def _canonical_field(field: pa.Field) -> pa.Field:
    """Return ``field`` with a canonical type and no metadata."""
    return field.with_type(_canonical_type(field.type)).remove_metadata()


def _canonical_type(data_type: pa.DataType) -> pa.DataType:
    """Return ``data_type`` with large offsets and ``uint32`` dictionary indices, recursively."""
    import pyarrow as pa

    types = pa.types
    if types.is_string(data_type) or types.is_string_view(data_type):
        return pa.large_string()
    if types.is_binary(data_type) or types.is_binary_view(data_type):
        return pa.large_binary()
    if types.is_list(data_type) or types.is_large_list(data_type) or types.is_list_view(data_type):
        return pa.large_list(_canonical_field(data_type.value_field))
    if types.is_struct(data_type):
        return pa.struct(
            [_canonical_field(data_type.field(i)) for i in range(data_type.num_fields)]
        )
    if types.is_dictionary(data_type):
        return pa.dictionary(pa.uint32(), _canonical_type(data_type.value_type), data_type.ordered)
    return data_type


def _frame_to_arrow(df: Any) -> pa.Table:
    """Convert a polars or pandas ``DataFrame`` to a pyarrow ``Table``.

    pandas frames drop their index.
    """
    import pyarrow as pa

    to_arrow = getattr(df, "to_arrow", None)
    if callable(to_arrow):
        # polars DataFrame.
        table = to_arrow()
        if isinstance(table, pa.Table):
            return table
    if _is_pandas_frame(df):
        return pa.Table.from_pandas(df, preserve_index=False)
    raise TypeError(f"Expected a polars or pandas DataFrame, got {type(df).__name__!r}.")


def _is_pandas_frame(obj: Any) -> bool:
    """Return whether ``obj`` is a pandas ``DataFrame``."""
    import pandas as pd

    return isinstance(obj, pd.DataFrame)


__all__ = [
    "MAX_FIGURE_SVG_BYTES",
    "SVG_CONTENT_TYPE",
    "SerialisedObject",
    "content_type_for",
    "figure_svg",
    "format_from_suffix",
    "serialise",
]
