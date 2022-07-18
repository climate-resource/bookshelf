import logging
import os
import tempfile
from glob import glob

import pytest

from bookshelf import BookShelf
from bookshelf.notebook import NOTEBOOK_DIRECTORY, run_notebook

logger = logging.getLogger("test-notebooks")

logger.info(f"Looking for notebooks in {NOTEBOOK_DIRECTORY}")
notebooks = glob(os.path.join(NOTEBOOK_DIRECTORY, "*.py"))

notebook_names = [os.path.basename(nb)[:-3] for nb in notebooks]
logger.info(f"Found {len(notebooks)} notebooks: {notebook_names}")


@pytest.fixture()
def output_directory():
    out_dir = os.environ.get("BOOKSHELF_CACHE_LOCATION", tempfile.mkdtemp())

    yield out_dir


@pytest.mark.parametrize("notebook_path", notebooks)
def test_notebook(notebook_path, output_directory):
    # Check that:
    # * notebooks run as expected
    # * that hash matches an existing notebook

    notebook = os.path.basename(notebook_path)[:-3]
    notebook_dir = os.path.dirname(notebook_path)

    shelf = BookShelf()

    target_book = run_notebook(
        notebook,
        nb_directory=notebook_dir,
        output_directory=os.path.join(output_directory, notebook),
    )

    if shelf.is_available(name=target_book.name, version=target_book.version):
        existing_book = shelf.load(
            name=target_book.name, version=target_book.version, force=True
        )
        logger.info(f"Remote book exists. Expecting hash: {existing_book.hash()}")

        if existing_book.hash() != target_book.hash():
            raise ValueError(
                f"Hash of calculated book doesn't match the remote bookshelf "
                f"({target_book.hash()} != {existing_book.hash()})"
            )
    else:
        logger.info("Book does not exist on remote bookshelf")
