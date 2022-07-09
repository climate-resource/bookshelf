from bookshelf import Book


def test_simple_book(local_bookshelf, remote_bookshelf):
    remote_bookshelf.register("test", "v1.1.0")

    book = Book("test", local_bookshelf=local_bookshelf)
    book.fetch()

    expected_dir = local_bookshelf / "test"
    assert (expected_dir / "volume.json").exists()
    assert (expected_dir / "v1.1.0" / "datapackage.json").exists()
