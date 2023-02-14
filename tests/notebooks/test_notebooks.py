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


def find_notebooks():
    NOTEBOOK_DIRECTORY = get_notebook_directory()

    logger.info(f"Looking for notebooks in {NOTEBOOK_DIRECTORY}")
    notebooks = glob(os.path.join(NOTEBOOK_DIRECTORY, "**", "*.py"), recursive=True)

    notebook_info = []

    for nb in notebooks:
        versions = get_available_versions(
            nb.replace(".py", ".yaml"), include_private=False
        )
        notebook_name = os.path.basename(nb)[:-3]
        notebook_info.extend((nb, notebook_name, v) for v in versions)

    logger.info(f"Found {len(notebook_info)} notebooks")
    for _, name, version in notebook_info:
        logger.info(f"Found {name}@{version}")
    return notebook_info


notebooks = find_notebooks()


@pytest.fixture()
def output_directory():
    out_dir = os.environ.get("BOOKSHELF_CACHE_LOCATION", tempfile.mkdtemp())

    yield out_dir


@pytest.mark.parametrize("notebook_path,notebook_name,notebook_version", notebooks)
def test_notebook(notebook_path, notebook_name, notebook_version, output_directory):
    # Check that:
    # * notebooks run as expected
    # * that hash matches an existing notebook

    notebook_dir = os.path.dirname(notebook_path)

    run_notebook_and_check_results(
        notebook_name,
        version=notebook_version,
        notebook_dir=notebook_dir,
        output_directory=os.path.join(
            output_directory, "sample", notebook_name, notebook_version
        ),
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

        if existing_book.edition != target_book.edition:
            raise ValueError(
                f"Edition of calculated book doesn't match the remote bookshelf "
                f"({target_book.edition} != {existing_book.edition})"
            )

        if existing_book.hash() != target_book.hash():
            raise ValueError(
                f"Hash of calculated book doesn't match the remote bookshelf "
                f"({target_book.hash()} != {existing_book.hash()})"
            )
    else:
        logger.info("Matching book version does not exist on remote bookshelf")
