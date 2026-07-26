"""Tests for the shared ``serialise`` materialisation step.

These exercise the single ``serialise -> hash`` function the live write path
and (later) the recording sink both reuse, so determinism is the headline
property: the same frame MUST yield identical bytes and an identical
``sha256:`` hash on every call, because record/replay byte-parity depends on
it.
"""

import hashlib
import io
from pathlib import Path

import polars as pl
import pytest

from bookshelf._produce.serialise import SerialisedObject, serialise


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "year": [2000, 2001, 2002],
            "value": [1.5, 2.5, 3.5],
            "region": ["a", "b", "c"],
        }
    )


def test_serialise_dataframe_is_deterministic() -> None:
    """The same frame serialises to identical bytes and hash across two calls."""
    df = _frame()
    first = serialise(df, type="timeseries")
    second = serialise(df, type="timeseries")

    assert first.data == second.data
    assert first.hash == second.hash
    # A fresh, equal frame (not the same object) lands on the same bytes too.
    assert serialise(_frame(), type="timeseries").data == first.data


def test_serialise_dataframe_hash_matches_content() -> None:
    """The returned hash is the canonical ``sha256:<hex>`` of the bytes."""
    result = serialise(_frame(), type="timeseries")
    assert result.hash == f"sha256:{hashlib.sha256(result.data).hexdigest()}"
    assert result.content_type == "application/vnd.apache.parquet"


def test_serialise_dataframe_round_trips_via_polars() -> None:
    """The parquet bytes read back through polars as the original frame."""
    df = _frame()
    result = serialise(df, type="timeseries")
    restored = pl.read_parquet(io.BytesIO(result.data))
    assert restored.equals(df)


def test_serialise_tabular_uses_parquet() -> None:
    """``tabular`` takes the same parquet path as ``timeseries``."""
    df = _frame()
    assert serialise(df, type="tabular").data == serialise(df, type="timeseries").data


def test_serialise_polars_and_pandas_agree() -> None:
    """A pandas frame serialises to the same bytes as the equivalent polars frame.

    Both convert through Arrow, so the shared writer yields identical bytes :
    which keeps a record produced by either frontend replayable.
    """
    df = _frame()
    pandas_bytes = serialise(df.to_pandas(), type="timeseries")
    assert pandas_bytes.data == serialise(df, type="timeseries").data


def test_serialise_document_passes_bytes_through() -> None:
    """A ``document`` blob is stored verbatim, hashed as-is."""
    blob = b'{"cells": [], "nbformat": 4}'
    result = serialise(blob, type="document")
    assert result == SerialisedObject(
        data=blob,
        hash=f"sha256:{hashlib.sha256(blob).hexdigest()}",
        content_type="application/octet-stream",
    )


def test_serialise_path_reads_file_bytes(tmp_path: Path) -> None:
    """A ``Path`` is read and stored verbatim regardless of resource type."""
    payload = b"<html><body>report</body></html>"
    path = tmp_path / "report.html"
    path.write_bytes(payload)

    result = serialise(path, type="document")
    assert result.data == payload
    assert result.hash == f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_serialise_prehashed_parquet_bytes_pass_through() -> None:
    """Already-serialised parquet bytes are not re-encoded for a parquet type."""
    buffer = io.BytesIO()
    _frame().write_parquet(buffer)
    raw = buffer.getvalue()

    result = serialise(raw, type="timeseries")
    assert result.data == raw
    assert result.content_type == "application/vnd.apache.parquet"


def test_serialise_rejects_dataframe_for_opaque_type() -> None:
    """A DataFrame for a non-parquet type is a usage error, not a silent pickle."""
    with pytest.raises(TypeError):
        serialise(_frame(), type="document")


# ----------------------------------------------------------------------
# Declared format: filled only when known with certainty.
# ----------------------------------------------------------------------
def test_serialise_dataframe_declares_parquet_format() -> None:
    """A client-encoded DataFrame is definitively parquet."""
    assert serialise(_frame(), type="timeseries").format == "parquet"
    assert serialise(_frame(), type="tabular").format == "parquet"


def test_serialise_bytes_claims_no_format() -> None:
    """Raw bytes pass through unclaimed: the format is unknowable."""
    assert serialise(b"anything", type="timeseries").format is None
    assert serialise(b"anything", type="document").format is None


def test_serialise_path_infers_format_from_suffix(tmp_path: Path) -> None:
    """A Path input names its format via the filename suffix."""
    cases = {
        "data.parquet": "parquet",
        "data.pq": "parquet",
        "data.csv": "csv",
        "data.csv.gz": "csv.gz",
        "data.CSV": "csv",
        "notebook.ipynb": None,
    }
    for name, expected in cases.items():
        p = tmp_path / name
        p.write_bytes(b"payload")
        assert serialise(p, type="tabular").format == expected, name
