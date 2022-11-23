import logging
import os
import tempfile
from glob import glob

import pytest

from bookshelf import BookShelf
from bookshelf.errors import UnknownBook
from bookshelf.notebook import (
    get_available_versions,
    get_notebook_directory,
    run_notebook,
)

logger = logging.getLogger("test-notebooks")

NOTEBOOK_DIRECTORY = get_notebook_directory()

logger.info(f"Looking for notebooks in {NOTEBOOK_DIRECTORY}")
notebooks = glob(os.path.join(NOTEBOOK_DIRECTORY, "**", "*.py"), recursive=True)

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

    versions = get_available_versions(notebook_path.replace(".py", ".yaml"))

    for v in versions:
        run_notebook_and_check_results(
            notebook,
            version=v,
            notebook_dir=notebook_dir,
            output_directory=os.path.join(output_directory, "sample", notebook, v),
        )


def run_notebook_and_check_results(notebook, version, notebook_dir, output_directory):
    shelf = BookShelf()

    try:
        target_book = run_notebook(
            notebook,
            nb_directory=notebook_dir,
            output_directory=output_directory,
            version=version,
        )
    except UnknownBook:
        logger.info("Book has not been pushed yet")
        return

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
        logger.info("Matching book version does not exist on remote bookshelf")
