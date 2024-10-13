import logging
import os
import sys
import tempfile
from glob import glob

import pytest

from bookshelf import BookShelf
from bookshelf.dataset_structure import verify_data_dictionary
from bookshelf.errors import UnknownBook
from bookshelf_producer.notebook import (
    get_available_versions,
    get_notebook_directory,
    load_nb_metadata,
    run_notebook,
)

logger = logging.getLogger("test-notebooks")


if sys.platform.startswith("win"):
    # https://github.com/climate-resource/bookshelf/issues/90
    pytest.skip("skipping notebook tests on windows, see issue #90", allow_module_level=True)


def find_notebooks():
    NOTEBOOK_DIRECTORY = get_notebook_directory()

    logger.info(f"Looking for notebooks in {NOTEBOOK_DIRECTORY}")
    notebooks = glob(os.path.join(NOTEBOOK_DIRECTORY, "**", "*.py"), recursive=True)

    notebook_info = []

    for nb in notebooks:
        versions = get_available_versions(nb.replace(".py", ".yaml"), include_private=False)
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


@pytest.mark.skip(reason="Migrating notebooks out of the repository for the next release")
@pytest.mark.parametrize("notebook_path,notebook_name,notebook_version", notebooks)
def test_notebook(notebook_path, notebook_name, notebook_version, output_directory):
    # Check that:
    # * notebooks run as expected
    # * that hash matches an existing notebook

    if notebook_name == "iea":
        pytest.xfail("IEA website is broken")

    notebook_dir = os.path.dirname(notebook_path)

    run_notebook_and_check_results(
        notebook_name,
        version=notebook_version,
        notebook_dir=notebook_dir,
        output_directory=os.path.join(output_directory, "sample", notebook_name, notebook_version),
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
        nb_metadata = load_nb_metadata(notebook, version, notebook_dir)

    except UnknownBook:
        logger.info("Book has not been pushed yet")
        return

    if shelf.is_available(name=target_book.name, version=target_book.version):
        existing_book = shelf.load(name=target_book.name, version=target_book.version, force=True)
        logger.info(f"Remote book exists. Expecting hash: {existing_book.hash()}")
        if existing_book.edition != target_book.edition:
            raise ValueError(
                "Edition of calculated book doesn't match the remote bookshelf "
                f"({target_book.edition} != {existing_book.edition})"
            )

        unique_files = []
        target_resources = target_book.metadata()["resources"]
        existing_resources = existing_book.metadata()["resources"]
        for i, target_resource in enumerate(target_resources):
            if target_resource["content_hash"] != existing_resources[i]["content_hash"]:
                raise ValueError(
                    "Hash of calculated file content doesn't match the remote bookshelf "
                    f"({target_resource['content_hash']}" + f" != {existing_resources[i]['content_hash']})"
                )

            name = target_resource["timeseries_name"]
            if name not in unique_files:
                unique_files.append(name)
                data = target_book.timeseries(name)
                verification = verify_data_dictionary(data, nb_metadata)
                if verification:
                    error_message = verification.error_message()
                    if error_message is not None:
                        pytest.xfail(error_message)
                else:
                    logger.warning(f"{notebook} does not contain data dictionary")

    else:
        logger.info("Matching book version does not exist on remote bookshelf")
