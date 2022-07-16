import pytest
import scmdata
import scmdata.testing

from bookshelf import Book


def test_simple_book(local_bookshelf, remote_bookshelf):
    remote_bookshelf.register("test", "v1.1.0")

    book = Book("test", local_bookshelf=local_bookshelf)
    book.fetch()

    expected_dir = local_bookshelf / "test"
    assert (expected_dir / "volume.json").exists()
    assert (expected_dir / "v1.1.0" / "datapackage.json").exists()


def test_existing(local_bookshelf, remote_bookshelf):
    remote_bookshelf.register("test", "v1.1.0")

    book = Book("test", local_bookshelf=local_bookshelf)
    book.fetch()
    remote_bookshelf.mocker.reset()

    new_book = Book("test", "v1.1.0", local_bookshelf=local_bookshelf)
    new_book.fetch()
    assert remote_bookshelf.mocker._adapter.call_count == 1

    assert book.metadata() == book.metadata()


def test_adding(local_bookshelf, example_data):
    book = Book.create_new("my_new_book", version="v0.1.0")
    assert len(book.metadata().resources) == 0

    book.add_timeseries("test", example_data)

    scmdata.testing.assert_scmdf_almost_equal(example_data, book.timeseries("test"))

    with pytest.raises(ValueError):
        book.timeseries("unknown")
