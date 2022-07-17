import json
import os
import shutil

import pytest
import scmdata

from bookshelf.constants import TEST_DATA_DIR
from bookshelf.utils import create_local_cache


def read_json(fname):
    fname = os.path.join(TEST_DATA_DIR, fname)
    with open(fname) as fh:
        return json.load(fh)


def read_data(fname):
    fname = os.path.join(TEST_DATA_DIR, fname)
    with open(fname) as fh:
        return fh.read()


@pytest.fixture(scope="function", autouse=True)
def local_bookshelf(tmpdir, monkeypatch):
    monkeypatch.setenv("BOOKSHELF_CACHE_LOCATION", tmpdir)
    fname = create_local_cache(tmpdir)
    yield fname

    shutil.rmtree(fname)


@pytest.fixture(scope="function", autouse=True)
def remote_bookshelf(requests_mock, monkeypatch):
    monkeypatch.setenv("BOOKSHELF_REMOTE", "https://bookshelf.local/v0.1.0")

    class MockRemoteBookshop:
        def __init__(self):
            self.mocker = requests_mock
            self.register("test", "v1.0.0")
            self.register("test", "v1.1.0")

        def register(self, name, version):
            requests_mock.get(
                f"https://bookshelf.local/v0.1.0/{name}/volume.json",
                json=read_json("v0.1.0/example/volume.json"),
            )
            requests_mock.get(
                f"https://bookshelf.local/v0.1.0/{name}/{version}/datapackage.json",
                json=read_json("v0.1.0/example/v1.0.0/datapackage.json"),
            )
            requests_mock.get(
                f"https://bookshelf.local/v0.1.0/{name}/{version}/leakage_rates_low.csv",
                raw=read_data("v0.1.0/example/v1.0.0/leakage_rates_low.csv"),
            )

    bs = MockRemoteBookshop()

    yield bs


@pytest.fixture()
def example_data():
    return scmdata.ScmRun(
        os.path.join(
            TEST_DATA_DIR, "v0.1.0", "example", "v1.0.0", "leakage_rates_low.csv"
        )
    )
