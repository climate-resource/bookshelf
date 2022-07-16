import pytest
import scmdata
import scmdata.testing

from bookshelf import LocalBook, BookShelf


def test_simple_book(local_bookshelf, remote_bookshelf):
    remote_bookshelf.register("test", "v1.1.0")

    shelf = BookShelf(path=local_bookshelf)
    book = shelf.load("test")

    expected_dir = local_bookshelf / "test"
    assert (expected_dir / "volume.json").exists()
    assert (expected_dir / "v1.1.0" / "datapackage.json").exists()


def test_adding(local_bookshelf, example_data):
    book = LocalBook.create_new(
        "my_new_book", version="v0.1.0", local_bookshelf=local_bookshelf
    )
    assert len(book.metadata().resources) == 0

    book.add_timeseries("test", example_data)

    scmdata.testing.assert_scmdf_almost_equal(example_data, book.timeseries("test"))

    with pytest.raises(ValueError):
        book.timeseries("unknown")
