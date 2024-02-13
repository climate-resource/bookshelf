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
                json=read_json("v0.2.0/example/v1.0.0_e001/datapackage.json"),
            )
            # only wide format data is currently return
            requests_mock.get(
                f"{url_prefix}/test_v1.0.0_e001_leakage_rates_low_wide.csv",
                text=read_data("v0.2.0/example/v1.0.0_e001/test_v1.0.0_e001_leakage_rates_low_wide.csv"),
            )

    bs = MockRemoteBookshelf()

    yield bs
