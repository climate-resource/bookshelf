"""
Re-useable fixtures etc. for tests

See https://docs.pytest.org/en/7.1.x/reference/fixtures.html#conftest-py-sharing-fixtures-across-multiple-files
"""

import json
import os
import shutil

import pandas as pd
import pytest
import scmdata

from bookshelf.constants import DATA_FORMAT_VERSION, TEST_DATA_DIR
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
                "v0.3.2",
                "example",
                "v1.0.0_e001",
                "test_v1.0.0_e001_leakage_rates_low_wide.csv",
            )
        )
        .timeseries()
        .sort_index()
    )


@pytest.fixture()
def example_long_format_data():
    return pd.read_csv(
        os.path.join(
            TEST_DATA_DIR,
            "v0.3.2",
            "example",
            "v1.0.0_e001",
            "test_v1.0.0_e001_leakage_rates_low_long.csv",
        )
    )


@pytest.fixture()
def example_unsorted_data():
    return scmdata.ScmRun(
        scmdata.ScmRun(
            os.path.join(
                TEST_DATA_DIR,
                "v0.3.2",
                "example",
                "v1.0.0_e001",
                "test_v1.0.0_e001_leakage_rates_low_wide_unsorted.csv",
            )
        ).timeseries()
    )


def read_json(fname):
    fname = os.path.join(TEST_DATA_DIR, fname)
    with open(fname) as fh:
        return json.load(fh)


def read_data(fname):
    fname = os.path.join(TEST_DATA_DIR, fname)
    with open(fname) as fh:
        return fh.read()


@pytest.fixture(scope="function", autouse=True)
def remote_bookshelf(requests_mock, monkeypatch):
    """
    Creates a mocked version of the RemoteBookshelf for testing purposes, allowing
    for the simulation of remote bookshelf interactions without actual network calls.

    This function leverages the `requests_mock` and `monkeypatch` fixtures to mock
    HTTP requests and environment variables, respectively. It defines and instantiates
    `MockRemoteBookshelf`, a class that simulates the behavior of a remote bookshelf
    by registering mock responses for specific book versions and editions.

    Yields
    ------
    MockRemoteBookshelf
        An instance of the mock class preconfigured with specific books and their data,
        enabling direct testing of functionalities that require bookshelf data access.

    Notes
    -----
    Mock data is sourced locally from the test-data folder in tests folder using the
    `read_data` function, which should be defined to load mock data files (e.g.,
    CSV, JSON) from the local file system.
    """

    prefix = f"https://bookshelf.local/{DATA_FORMAT_VERSION}"
    monkeypatch.setenv("BOOKSHELF_REMOTE", prefix)

    class MockRemoteBookshelf:
        def __init__(self):
            self.mocker = requests_mock
            self.meta = {}

            self.register("test", "v1.0.0", 1)
            self.register("test", "v1.1.0", 1)

        def register(self, name, version, edition, private=False):
            if name not in self.meta:
                self.meta[name] = {
                    "name": name,
                    "license": "MIT",
                    "versions": [],
                }

            url_prefix = f"{prefix}/{name}/{version}_e{edition:03}"
            self.meta[name]["versions"].append(
                {
                    "version": version,
                    "edition": edition,
                    "hash": "",
                    "url": url_prefix,
                    "private": private,
                }
            )
            requests_mock.get(
                f"{prefix}/{name}/volume.json",
                json=self.meta[name],
            )
            requests_mock.get(
                f"{url_prefix}/datapackage.json",
                json=read_json("v0.3.1/example/v1.0.0_e001/datapackage.json"),
            )
            requests_mock.get(
                f"{url_prefix}/{name}_v1.0.0_e001_leakage_rates_low_wide.csv",
                text=read_data("v0.3.1/example/v1.0.0_e001/test_v1.0.0_e001_leakage_rates_low_wide.csv"),
            )

    bs = MockRemoteBookshelf()

    yield bs
