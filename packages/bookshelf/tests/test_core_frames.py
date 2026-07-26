"""DataFrame round-trip tests for the ``/data`` frame-conversion parse layer."""

import io
import json

import pandas as pd
import pandas.testing as pdt

from bookshelf._core.frames import to_pandas
from bookshelf._core.types import DataPayload


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"region": ["NZL", "AUS"], "year": [2000, 2001], "value": [1.5, 2.5]})


def test_parquet_round_trip() -> None:
    buffer = io.BytesIO()
    _frame().to_parquet(buffer)
    result = to_pandas(DataPayload(format="parquet", content=buffer.getvalue()))
    pdt.assert_frame_equal(result, _frame())


def test_csv_round_trip() -> None:
    content = _frame().to_csv(index=False).encode()
    result = to_pandas(DataPayload(format="csv", content=content))
    pdt.assert_frame_equal(result, _frame())


def test_json_rows_round_trip() -> None:
    content = json.dumps(_frame().to_dict(orient="records")).encode()
    result = to_pandas(DataPayload(format="json", content=content))
    pdt.assert_frame_equal(result, _frame())
