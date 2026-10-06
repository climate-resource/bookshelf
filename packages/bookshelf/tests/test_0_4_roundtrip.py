"""Round trip: what bookshelf 0.4.3 read from S3 is what bookshelf reads from the platform.

This needs a live deployment, so it runs only when ``BOOKSHELF_URL`` points at one:

    BOOKSHELF_URL=https://bookshelf-staging.ovh.climateresource.com.au uv run pytest -m integration

The fixtures under ``inputs/legacy`` were recorded once with the old library
against its default S3 bucket, for ``primap-hist`` v2.6 e5 resource ``by_country``,
filtered to New Zealand's country reported series because the whole frame is 67MB.
Roughly, with ``uvx --python 3.12 --from bookshelf==0.4.3 --with pyarrow python``::

    shelf = bookshelf.BookShelf()
    run = shelf.load("primap-hist", "v2.6", 5).timeseries("by_country").filter(**SUBSET)
    wide = run.timeseries()
    wide.columns = [str(c.year) for c in wide.columns]
    wide = wide.reset_index()
    for c in run.meta.columns:
        wide[c] = wide[c].where(wide[c].isna(), wide[c].astype(str))
    wide.to_parquet("by_country_wide.parquet", index=False, compression="brotli")

    scratch = LocalBook.create_new("primap-hist", "v2.6", 5, local_bookshelf=tmp)
    scratch.add_timeseries("by_country", run)
    long = scratch.get_long_format_data("by_country")
    long["category"] = long["category"].where(long["category"].isna(), long["category"].astype(str))
    long.to_parquet("by_country_long.parquet", index=False, compression="brotli")

That book carries no ``by_country_long`` resource on S3,
so the long fixture comes from the 0.4 writer run over the same data.

Two quirks of the old CSV round trip are normalised before comparing, because they are
artefacts of the old reader rather than of the data:

- ``category`` came back as a mix of ints and strings, so it is stored as text
  and both sides are sorted the same way instead of trusting the old sort order.
- an empty ``gwp_context`` came back as NaN, where the platform keeps the empty string.
"""

import os
from pathlib import Path

import pandas as pd
import pytest

from bookshelf import Bookshelf, Resource
from bookshelf.cache import ContentCache

INPUTS = Path(__file__).parent / "inputs" / "legacy"
SUBSET = {"country": "New Zealand", "scenario": "Historical|Country Reported"}
DIMENSIONS = [
    "category",
    "country",
    "gwp_context",
    "model",
    "provenance",
    "region",
    "scenario",
    "source",
    "unit",
    "variable",
]


def _comparable(frame: pd.DataFrame, sort_by: list[str]) -> pd.DataFrame:
    """Sort one way and read an empty dimension as the empty string, on both sides."""
    frame = frame.copy()
    frame[DIMENSIONS] = frame[DIMENSIONS].fillna("")
    return frame.sort_values(sort_by, kind="stable").reset_index(drop=True)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("BOOKSHELF_URL"),
        reason="set BOOKSHELF_URL to a live deployment to run the round trip",
    ),
]


@pytest.fixture(scope="module")
def resource(tmp_path_factory: pytest.TempPathFactory) -> Resource:
    shelf = Bookshelf(cache=ContentCache(tmp_path_factory.mktemp("cache")))
    return shelf.book("primap-hist", "v2.6", edition=5)["by_country"].as_resource()


def test_timeseries_matches_the_0_4_read(resource: Resource) -> None:
    pytest.importorskip("scmdata")
    expected = pd.read_parquet(INPUTS / "by_country_wide.parquet")

    run = resource.as_scmrun().filter(**SUBSET)

    wide = run.timeseries()
    wide.columns = [str(time.year) for time in wide.columns]
    actual = wide.reset_index()[expected.columns]
    pd.testing.assert_frame_equal(
        _comparable(actual, DIMENSIONS), _comparable(expected, DIMENSIONS)
    )


def test_legacy_columns_matches_the_0_4_writer(resource: Resource) -> None:
    expected = pd.read_parquet(INPUTS / "by_country_long.parquet")

    with pytest.warns(DeprecationWarning, match="legacy_columns"):
        long = resource.as_long_df(legacy_columns=True)

    actual = long[(long[list(SUBSET)] == pd.Series(SUBSET)).all(axis="columns")]
    assert list(actual.columns) == list(expected.columns)
    pd.testing.assert_frame_equal(
        _comparable(actual, [*DIMENSIONS, "year"]), _comparable(expected, [*DIMENSIONS, "year"])
    )
