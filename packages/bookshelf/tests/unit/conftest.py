import json
import os

import pytest

from bookshelf.constants import DATA_FORMAT_VERSION, TEST_DATA_DIR


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
            self.register_with_dataframe("example_with_dataframe", "v1.0.0", 1)

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

        def register_with_dataframe(self, name, version, edition, private=False):
            """Register a book that contains DataFrame resources."""
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
                json=read_json(f"v0.3.2/{name}/volume.json"),
            )
            requests_mock.get(
                f"{url_prefix}/datapackage.json",
                json=read_json(f"v0.3.2/{name}/{version}_e{edition:03}/datapackage.json"),
            )
            # Register the parquet file
            parquet_filename = f"{name}_{version}_e{edition:03}_country_metadata.parquet.gz"
            parquet_path = os.path.join(
                TEST_DATA_DIR, f"v0.3.2/{name}/{version}_e{edition:03}/{parquet_filename}"
            )
            with open(parquet_path, "rb") as f:
                parquet_content = f.read()
            requests_mock.get(
                f"{url_prefix}/{parquet_filename}",
                content=parquet_content,
            )

    bs = MockRemoteBookshelf()

    yield bs
