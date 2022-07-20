import os.path
import re
import tempfile

import pytest

import bookshelf.notebook
from bookshelf.notebook import load_nb_metadata, run_notebook


def test_load_nb_metadata():
    res = load_nb_metadata("example")

    assert res.name == "example"


def test_load_nb_metadata_paths():
    exp = load_nb_metadata("example")
    assert load_nb_metadata("example")
    assert load_nb_metadata("example.yaml") == exp
    nb_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "notebooks", "example.yaml"
    )
    assert load_nb_metadata(os.path.abspath(nb_dir)) == exp


def test_run_notebook():
    with tempfile.TemporaryDirectory() as td:
        book = run_notebook("example", output_directory=str(td))

        with pytest.raises(ValueError, match=f"{td} is not empty"):
            run_notebook("example", output_directory=str(td))
        run_notebook("example", output_directory=str(td), force=True)

        assert len(book.files()) == 2
        assert sorted(os.listdir(str(td))) == sorted(
            [
                "example",  # output
                "example.ipynb",
                "example.yaml",
                "example.py",
            ]
        )


@pytest.mark.parametrize("package", ["jupytext", "papermill"])
def test_missing_deps(package):
    try:
        setattr(bookshelf.notebook, f"has_{package}", False)

        match = re.escape(
            f"{package} is not installed. Run 'pip install bookshelf[notebooks]'"
        )
        with pytest.raises(ImportError, match=match):
            run_notebook("test")
    finally:
        bookshelf.notebook.has_papermill = True
        bookshelf.notebook.has_jupytext = True
