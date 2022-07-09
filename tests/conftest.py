import json
import os
import shutil
import pytest
from bookshelf.utils import create_local_cache
from bookshelf.constants import TEST_DATA_DIR


def read_json(fname):
    fname = os.path.join(TEST_DATA_DIR, fname)
    with open(fname) as fh:
        return json.load(fh)


def read_data(fname):
    fname = os.path.join(TEST_DATA_DIR, fname)
    with open(fname) as fh:
        return fh.read()


@pytest.fixture(scope="function")
def local_bookshelf(tmpdir):
    fname = create_local_cache(tmpdir)
    yield fname

    shutil.rmtree(fname)


@pytest.fixture(scope="function")
def remote_bookshelf(requests_mock):
    class MockRemoteBookshop:
        def __init__(self):
            self.mocker = requests_mock

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
