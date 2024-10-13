import os

import pytest

from bookshelf import LocalBook
from bookshelf_producer.notebook import run_notebook


@pytest.fixture
def primap_book(local_bookshelf: os.PathLike) -> LocalBook:
    # Run the latest primap notebook and return the results
    yield run_notebook("primap-hist", output_directory=str(local_bookshelf))


@pytest.mark.xfail(reason=("scmdata reading bug: https://github.com/climate-resource/bookshelf/issues/87"))
def test_primap_categories(primap_book, local_bookshelf):
    # Read the PRIMAP results from the local bookshelf
    emissions = primap_book.timeseries("by_country")
    assert emissions.get_unique_meta("category") == [
        "0",
        "1",
        "1.A",
        "1.B",
        "1.B.1",
        "1.B.2",
        "1.B.3",
        "2",
        "2.A",
        "2.B",
        "2.C",
        "2.D",
        "2.G",
        "2.H",
        "3",
        "3.A",
        "4",
        "5",
        "M.0.EL",
        "M.AG",
        "M.AG.ELV",
        "M.LULUCF",
    ]


def test_primap_units(primap_book, local_bookshelf):
    emissions = primap_book.timeseries("by_region")
    assert emissions.get_unique_meta("unit") == [
        "kt CO2 / yr",
        "kt CH4 / yr",
        "kt N2O / yr",
        "kt NF3 / yr",
        "kt SF6 / yr",
    ]
