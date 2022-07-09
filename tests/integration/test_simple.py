from bookshelf import Book


def test_simple_book(local_bookshelf, remote_bookshelf):
    remote_bookshelf.register("test", "v1.0.0")

    book = Book("test")
    book.fetch()

    expected_dir = local_bookshelf / "test"
    assert (expected_dir / "datapackage.json").exists()
