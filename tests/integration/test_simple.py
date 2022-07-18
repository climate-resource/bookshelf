from bookshelf import BookShelf


# Fetches from the remote bookshelf
def test_simple_book(local_bookshelf, caplog):
    with caplog.at_level(level="INFO"):
        shelf = BookShelf()
        shelf.load("rcmip-emissions", "v0.0.2")

    expected_dir = local_bookshelf / "rcmip-emissions"
    # assert (expected_dir / "volume.json").exists()
    assert (expected_dir / "v0.0.2" / "datapackage.json").exists()
