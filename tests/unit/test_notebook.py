import os.path
import re
import tempfile

import pytest

import bookshelf.notebook
from bookshelf.errors import UnknownVersion
from bookshelf.notebook import get_notebook_directory, load_nb_metadata, run_notebook


def test_load_nb_metadata():
    res = load_nb_metadata(
        "simple",
        nb_directory=os.path.join(get_notebook_directory(), "examples", "simple"),
    )

    assert res.name == "simple"


def test_load_nb_metadata_versioned():
    # Use the default version suffix
    res = load_nb_metadata(
        "multiple_versions",
        version="v5.1.0",
        nb_directory=os.path.join(
            get_notebook_directory(), "examples", "multiple_versions"
        ),
    )
    assert res.name == "multiple_versions"
    assert res.version == "v5.1.0"

    # Be explicit
    res = load_nb_metadata(
        "multiple_versions",
        nb_directory=os.path.join(
            get_notebook_directory(), "examples", "multiple_versions"
        ),
        version="v4.0.0",
    )
    assert res.name == "multiple_versions"
    assert res.version == "v4.0.0"

    with pytest.raises(UnknownVersion):
        load_nb_metadata(
            "examples/multiple_versions",
            version="v1.0.0",
        )


def test_load_nb_metadata_paths():
    simple_nb_dir = os.path.join(get_notebook_directory(), "examples", "simple")

    load_nb_metadata("simple", nb_directory=simple_nb_dir)
    load_nb_metadata("examples/simple")
    load_nb_metadata("examples/simple/simple.yaml")
    exp = load_nb_metadata(
        "simple",
        nb_directory=os.path.join(get_notebook_directory(), "examples"),
    )
    assert exp
    assert load_nb_metadata("simple.yaml", nb_directory=simple_nb_dir) == exp
    nb_dir = os.path.join(simple_nb_dir, "simple.yaml")
    assert load_nb_metadata(os.path.abspath(nb_dir)) == exp


def test_run_notebook(remote_bookshelf):
    simple_nb_dir = os.path.join(get_notebook_directory(), "examples", "simple")
    remote_bookshelf.register("simple", "v0.1.0", 1)

    with tempfile.TemporaryDirectory() as td:
        book = run_notebook(
            "simple", nb_directory=simple_nb_dir, output_directory=str(td)
        )

        with pytest.raises(ValueError, match=f"{td} is not empty"):
            run_notebook("simple", nb_directory=simple_nb_dir, output_directory=str(td))
        run_notebook("examples/simple", output_directory=str(td), force=True)

        assert len(book.files()) == 2
        assert sorted(os.listdir(str(td))) == sorted(
            [
                "simple",  # output
                "simple.ipynb",
                "simple.yaml",
                "simple.py",
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
