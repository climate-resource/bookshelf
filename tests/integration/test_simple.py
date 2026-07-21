import pytest

from bookshelf import BookShelf


@pytest.fixture(autouse=True)
def remote_bookshelf():
    # Disable the remote bookshelf fixture for this test
    return


# Fetches from the remote bookshelf
def test_simple_book(local_bookshelf, caplog):
    with caplog.at_level(level="INFO"):
        shelf = BookShelf()
        rcmip_book = shelf.load("rcmip-emissions", "v5.1.0")

    expected_dir = local_bookshelf / "rcmip-emissions"
    # assert (expected_dir / "volume.json").exists()
    assert (expected_dir / "v5.1.0_e001" / "datapackage.json").exists()

    metadata = rcmip_book.metadata()
    assert metadata["version"] == "v5.1.0"
    assert len(metadata["resources"])

    magicc = rcmip_book.timeseries("magicc")
    assert len(magicc)
    assert (expected_dir / "v5.1.0_e001" / "rcmip-emissions_v5.1.0_e001_magicc_wide.csv.gz").exists()
