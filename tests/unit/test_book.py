import os

import datapackage
import pooch.hashes
import pytest
import scmdata.testing

from bookshelf.book import LocalBook
from bookshelf.constants import DATA_FORMAT_VERSION, TEST_DATA_DIR
from bookshelf.shelf import BookShelf


def test_book_info():
    book = LocalBook("missing", "v1.1.0")
    assert book.name == "missing"
    assert book.version == "v1.1.0"


def test_book_without_metadata():
    book = LocalBook("missing", "v1.0.0")
    with pytest.raises(FileNotFoundError):
        book.metadata()


def test_create_local(local_bookshelf):
    expected_fname = local_bookshelf / "test" / "v1.0.0_e001" / "datapackage.json"

    assert not expected_fname.exists()
    LocalBook.create_new("test", "v1.0.0", local_bookshelf=local_bookshelf)
    assert expected_fname.exists()


def test_add_timeseries(local_bookshelf, example_data):
    book = LocalBook.create_new("test", "v1.1.0", local_bookshelf=local_bookshelf)
    book.add_timeseries("test", example_data)
    assert len(book.as_datapackage().resources) == 1

    expected_fname = local_bookshelf / "test" / "v1.1.0_e001" / "test.csv"
    assert expected_fname.exists()

    res = book.as_datapackage().resources[0]
    assert res.name == "test"
    assert res.descriptor["format"] == "CSV"
    assert res.descriptor["filename"] == "test.csv"
    assert res.descriptor["hash"] == pooch.hashes.file_hash(expected_fname)


def test_timeseries(example_data):
    book = LocalBook.create_new("test", "v1.1.0")
    book.add_timeseries("test", example_data)

    scmdata.testing.assert_scmdf_almost_equal(example_data, book.timeseries("test"))

    with pytest.raises(ValueError, match="Unknown timeseries 'other'"):
        book.timeseries("other")


def test_timeseries_remote(example_data, remote_bookshelf):
    book = BookShelf().load("test", "v1.0.0")

    scmdata.testing.assert_scmdf_almost_equal(
        example_data, book.timeseries("leakage_rates_low")
    )

    with pytest.raises(ValueError, match="Unknown timeseries 'other'"):
        book.timeseries("other")


def test_metadata():
    book = LocalBook(
        "example",
        "v1.0.0",
        local_bookshelf=os.path.join(TEST_DATA_DIR, DATA_FORMAT_VERSION),
    )

    package = book.as_datapackage()

    assert isinstance(package, datapackage.Package)

    meta_dict = package.descriptor
    assert meta_dict["name"] == book.name
    assert meta_dict["version"] == book.version

    assert meta_dict == book.metadata()


def test_metadata_missing():
    book = LocalBook("example", "v1.0.0")
    with pytest.raises(FileNotFoundError):
        book.metadata()


def test_files(local_bookshelf):
    book = LocalBook("example", "v1.0.0")

    assert len(book.files()) == 0

    book = LocalBook(
        "example",
        "v1.0.0",
        local_bookshelf=os.path.join(TEST_DATA_DIR, DATA_FORMAT_VERSION),
    )
    assert len(book.files()) == 2

    book = LocalBook.create_new("example", "v1.1.0", local_bookshelf=local_bookshelf)
    book_files = book.files()
    assert len(book_files) == 1
    assert book_files[0] == os.path.join(book.local_fname("datapackage.json"))
