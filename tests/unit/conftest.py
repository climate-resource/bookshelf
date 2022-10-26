import json
import os

import pytest

from bookshelf.constants import TEST_DATA_DIR


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
    monkeypatch.setenv("BOOKSHELF_REMOTE", "https://bookshelf.local/v0.2.0")

    class MockRemoteBookshelf:
        def __init__(self):
            self.mocker = requests_mock
            self.meta = {}

            self.register("test", "v1.0.0", 1)
            self.register("test", "v1.1.0", 1)

        def register(self, name, version, edition):
            if name not in self.meta:
                self.meta[name] = {
                    "name": name,
                    "license": "MIT",
                    "versions": [],
                }

            url_prefix = (
                f"https://bookshelf.local/v0.2.0/{name}/{version}_e{edition:03}"
            )
            self.meta[name]["versions"].append(
                {
                    "version": version,
                    "edition": edition,
                    "hash": "",
                    "url": url_prefix,
                }
            )
            requests_mock.get(
                f"https://bookshelf.local/v0.2.0/{name}/volume.json",
                json=self.meta[name],
            )
            requests_mock.get(
                f"{url_prefix}/datapackage.json",
                json=read_json("v0.2.0/example/v1.0.0_e001/datapackage.json"),
            )
            requests_mock.get(
                f"{url_prefix}/leakage_rates_low.csv",
                text=read_data("v0.2.0/example/v1.0.0_e001/leakage_rates_low.csv"),
            )

    bs = MockRemoteBookshelf()

    yield bs
