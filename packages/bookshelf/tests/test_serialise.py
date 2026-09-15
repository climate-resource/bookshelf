"""Tests for the shared ``serialise`` materialisation step.

These exercise the single ``serialise -> hash`` function the live write path
and (later) the recording sink both reuse, so determinism is the headline
property: the same frame MUST yield identical bytes and an identical
``sha256:`` hash on every call, because record/replay byte-parity depends on
it.
"""

import hashlib
import io
import struct
from pathlib import Path

import polars as pl
import pyarrow as pa
import pytest
from matplotlib.figure import Figure

from bookshelf._produce import serialise as serialise_module
from bookshelf._produce.serialise import (
    SerialisedObject,
    content_type_for,
    figure_svg,
    serialise,
)


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


@pytest.mark.parametrize(
    "column",
    [
        pytest.param(pl.Series(["a", None]), id="string"),
        pytest.param(pl.Series([b"x", b"y"]), id="binary"),
        pytest.param(pl.Series([[1], [2, 3]]), id="list"),
        pytest.param(pl.Series([["a"], ["b", "c"]]), id="list-of-string"),
        pytest.param(pl.Series([{"k": "a"}, {"k": "b"}]), id="struct"),
        pytest.param(pl.Series(["a", "b", "a"], dtype=pl.Categorical), id="categorical"),
    ],
)
def test_serialise_polars_and_pandas_agree_per_column_type(column: pl.Series) -> None:
    """pandas and polars pick different Arrow offset and index widths, which must not reach the bytes."""
    df = pl.DataFrame({"column": column})

    assert serialise(df.to_pandas(), type="tabular").data == serialise(df, type="tabular").data


class _ArrowFrame:
    """A frame whose ``to_arrow`` hands back a prepared table, as polars does."""

    def __init__(self, table: pa.Table) -> None:
        self._table = table

    def to_arrow(self) -> pa.Table:
        return self._table


def test_serialise_view_types_match_their_offset_equivalents() -> None:
    """A frontend that switches to Arrow view types must not change the bytes."""
    plain = pa.table(
        {
            "s": pa.array(["a", None], pa.large_string()),
            "b": pa.array([b"x", b"y"], pa.large_binary()),
        }
    )
    views = pa.table(
        {
            "s": pa.array(["a", None], pa.string_view()),
            "b": pa.array([b"x", b"y"], pa.binary_view()),
        }
    )

    assert (
        serialise(_ArrowFrame(views), type="tabular").data
        == serialise(_ArrowFrame(plain), type="tabular").data
    )


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


def _figure() -> Figure:
    fig = Figure()
    fig.add_subplot().bar(["a", "b", "c"], [1.5, 2.5, 3.5])
    return fig


def _png_width(data: bytes) -> int:
    width: int = struct.unpack(">I", data[16:20])[0]
    return width


def test_serialise_figure_is_deterministic() -> None:
    fig = _figure()

    assert serialise(fig, type="figure").hash == serialise(fig, type="figure").hash


def test_serialise_figure_leaves_the_matplotlib_version_out() -> None:
    assert b"Matplotlib version" not in serialise(_figure(), type="figure").data


def test_serialise_figure_is_a_png_master_2400_px_wide() -> None:
    result = serialise(_figure(), type="figure")

    assert result.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert _png_width(result.data) == 2400
    assert (result.content_type, result.format) == ("image/png", "png")


def test_serialise_figure_refuses_bytes_that_are_not_a_png() -> None:
    with pytest.raises(ValueError, match="png"):
        serialise(b"not a png", type="figure")


def test_serialise_figure_refuses_a_path_that_is_not_a_png(tmp_path: Path) -> None:
    path = tmp_path / "figure.png"
    path.write_bytes(b"not a png")

    with pytest.raises(ValueError, match="png"):
        serialise(path, type="figure")


def test_serialise_figure_passes_a_png_path_through(tmp_path: Path) -> None:
    data = serialise(_figure(), type="figure").data
    path = tmp_path / "figure.png"
    path.write_bytes(data)

    result = serialise(path, type="figure")

    assert (result.data, result.format, result.content_type) == (data, "png", "image/png")


def test_content_type_for_a_figure_is_png() -> None:
    assert content_type_for("figure") == "image/png"


def test_figure_svg_saves_the_same_bytes_twice() -> None:
    fig = _figure()

    assert figure_svg(fig) == figure_svg(fig)


def test_figure_svg_of_two_equal_figures_agrees() -> None:
    assert figure_svg(_figure()) == figure_svg(_figure())


def test_figure_svg_is_an_svg_without_a_date() -> None:
    data = figure_svg(_figure())

    assert data is not None
    assert b"<svg" in data
    assert b"<dc:date>" not in data


def test_figure_svg_returns_none_for_bytes_and_a_path(tmp_path: Path) -> None:
    data = serialise(_figure(), type="figure").data
    path = tmp_path / "figure.png"
    path.write_bytes(data)

    assert figure_svg(data) is None
    assert figure_svg(path) is None


def test_figure_svg_over_the_size_cap_returns_none_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(serialise_module, "MAX_FIGURE_SVG_BYTES", 10)

    with caplog.at_level("WARNING", logger="bookshelf._produce.serialise"):
        result = figure_svg(_figure())

    assert result is None
    assert len(caplog.records) == 1
    assert "10 byte limit" in caplog.records[0].getMessage()
