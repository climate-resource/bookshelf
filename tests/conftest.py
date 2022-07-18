import os
import shutil

import pytest
import scmdata

from bookshelf.constants import TEST_DATA_DIR
from bookshelf.utils import create_local_cache


@pytest.fixture(scope="function", autouse=True)
def local_bookshelf(tmpdir, monkeypatch):
    monkeypatch.setenv("BOOKSHELF_CACHE_LOCATION", str(tmpdir))
    fname = create_local_cache(tmpdir)
    yield fname

    shutil.rmtree(fname)


@pytest.fixture()
def example_data():
    return scmdata.ScmRun(
        os.path.join(
            TEST_DATA_DIR, "v0.1.0", "example", "v1.0.0", "leakage_rates_low.csv"
        )
    )
