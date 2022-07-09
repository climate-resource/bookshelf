import json
import os
import shutil
import pytest
from bookshelf.utils import create_local_cache
from bookshelf.constants import TEST_DATA_DIR


def read_json(fname):
    fname = os.path.join(TEST_DATA_DIR, fname)
    with open(fname) as fh:
        json.load(fh)


@pytest.fixture(scope="function")
def local_bookshelf(tmpdir):
    fname = create_local_cache(tmpdir)
    yield fname

    shutil.rmtree(fname)


@pytest.fixture(scope="function")
def remote_bookshelf(requests_mock):
    class MockBook:
        def __init__(self, name, version):
            pass

        def meta(self):
            pass

    class MockRemoteBookshop:
        def __init__(self):
            self.books = []
            self.mocker = requests_mock

        def register(self, name, version):
            requests_mock.get(
                f"https://bookshelf.local/v0.1.0/{name}/volume.json",
                json=read_json("v0.1.0/example/volume.json"),
            )
            self.books.append(MockBook(name, version))

    bs = MockRemoteBookshop()

    yield bs
