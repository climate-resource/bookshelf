"""
Re-useable fixtures etc. for tests

See https://docs.pytest.org/en/7.1.x/reference/fixtures.html#conftest-py-sharing-fixtures-across-multiple-files
"""
import os
import shutil

import pandas as pd
import pytest
import scmdata

from bookshelf.constants import TEST_DATA_DIR
from bookshelf.utils import create_local_cache


@pytest.fixture(scope="session", autouse=True)
def pandas_terminal_width():
    # Set pandas terminal width so that doctests don't depend on terminal width.

    # We set the display width to 120 because examples should be short,
    # anything more than this is too wide to read in the source.
    pd.set_option("display.width", 120)

    # Display as many columns as you want (i.e. let the display width do the
    # truncation)
    pd.set_option("display.max_columns", 1000)


@pytest.fixture(scope="function", autouse=True)
def local_bookshelf(tmpdir, monkeypatch):
    monkeypatch.setenv("BOOKSHELF_CACHE_LOCATION", str(tmpdir))
    fname = create_local_cache(tmpdir)
    yield fname

    shutil.rmtree(fname)


@pytest.fixture()
def example_data():
    return scmdata.ScmRun(
        scmdata.ScmRun(
            os.path.join(
                TEST_DATA_DIR,
                "v0.2.0",
                "example",
                "v1.0.0_e001",
                "test_v1.0.0_e001_leakage_rates_low_wide.csv",
            )
        )
        .timeseries()
        .sort_index()
    )
