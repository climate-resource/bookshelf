import os

import datapackage
import pooch.hashes
import pytest

from bookshelf.book import LocalBook
from bookshelf.constants import TEST_DATA_DIR, DATA_FORMAT_VERSION


def test_book_info():
    book = LocalBook("missing", "v1.1.0")
    assert book.name == "missing"
    assert book.version == "v1.1.0"


def test_book_without_metadata():
    book = LocalBook("missing", "v1.0.0")
    with pytest.raises(FileNotFoundError):
        book.metadata()


def test_create_local(local_bookshelf):
    expected_fname = local_bookshelf / "test" / "v1.0.0" / "datapackage.json"

    assert not expected_fname.exists()
    LocalBook.create_new("test", "v1.0.0", local_bookshelf=local_bookshelf)
    assert expected_fname.exists()


def test_add_timeseries(local_bookshelf, example_data):
    book = LocalBook.create_new("test", "v1.1.0", local_bookshelf=local_bookshelf)
    book.add_timeseries("test", example_data)
    assert len(book.metadata().resources) == 1

    expected_fname = local_bookshelf / "test" / "v1.1.0" / "test.csv"
    assert expected_fname.exists()

    res = book.metadata().resources[0]
    assert res.name == "test"
    assert res.descriptor["format"] == "CSV"
    assert res.descriptor["filename"] == "test.csv"
    assert res.descriptor["hash"] == pooch.hashes.file_hash(expected_fname)


def test_metadata():
    book = LocalBook(
        "example",
        "v1.0.0",
        local_bookshelf=os.path.join(TEST_DATA_DIR, DATA_FORMAT_VERSION),
    )

    metadata = book.metadata()

    assert isinstance(metadata, datapackage.Package)

    meta_dict = metadata.to_dict()
    assert meta_dict["name"] == book.name
    assert meta_dict["version"] == book.version
