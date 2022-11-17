from bookshelf import BookShelf


# Fetches from the remote bookshelf
def test_simple_book(local_bookshelf, caplog):
    with caplog.at_level(level="INFO"):
        shelf = BookShelf()
        shelf.load("rcmip-emissions", "v5.1.0")

    expected_dir = local_bookshelf / "rcmip-emissions"
    # assert (expected_dir / "volume.json").exists()
    assert (expected_dir / "v5.1.0_e001" / "datapackage.json").exists()
