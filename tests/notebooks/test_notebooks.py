import logging
import os
import sys
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


if sys.platform.startswith("win"):
    # https://gitlab.com/climate-resource/bookshelf/bookshelf/-/issues/23
    pytest.skip("skipping notebook tests on windows, see issue !23", allow_module_level=True)


def find_notebooks():
    NOTEBOOK_DIRECTORY = get_notebook_directory()

    logger.info(f"Looking for notebooks in {NOTEBOOK_DIRECTORY}")
    notebooks = glob(os.path.join(NOTEBOOK_DIRECTORY, "**", "*.py"), recursive=True)

    notebook_info = []

    for nb in notebooks:
        versions = get_available_versions(nb.replace(".py", ".yaml"), include_private=True)
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
        output_directory=os.path.join(output_directory, "sample", notebook_name, notebook_version),
    )


# def verify_data_dictionary(data, yaml_file):
#     verification = {
#         "col_name_macth": True,
#         "col_type_match": True,
#         "controlled_vocabulary_match": True,
#         "non_na_col_match": True,
#         "model_validate_true": True,
#     }
#     if "data_dictionary" not in yaml_file[1].keys():
#         return None
#     else:
#         data_dictionary = yaml_file[1]["data_dictionary"]
#         if len(data_dictionary) == len(data.meta.columns):
#             unique_values = dataset_structure.get_dataset_dictionary(data)
#             for variable in data_dictionary:
#                 if variable["name"] not in data.meta.columns:
#                     verification["col_name_macth"] = False
#                 else:
#                     try:
#                         data.meta[variable["name"]].astype(variable["type"])
#                     except:
#                         verification["col_type_match"] = False
#                     if "controlled_vocabulary" in variable.keys():
#                         if not set(unique_values[variable["name"]]).issubset(
#                             set([i["value"] for i in variable["controlled_vocabulary"]])
#                         ):
#                             verification["controlled_vocabulary_match"] = False
#                     if variable["required"]:
#                         if data.meta[variable["name"]].isnull().any():
#                             verification["non_na_col_match"] = False
#         else:
#             verification["col_name_macth"] = False
#         return verification


def run_notebook_and_check_results(notebook, version, notebook_dir, output_directory):
    shelf = BookShelf()

    try:
        target_book = run_notebook(
            notebook,
            nb_directory=notebook_dir,
            output_directory=output_directory,
            version=version,
        )
        # yaml_file = _load_nb_config(notebook_dir)
        # # import pdb; pdb.set_trace()
        # time_series_names = [i['name'] for i in target_book.metadata()['resources']]

        # for name in time_series_names:
        #     df = target_book.timeseries(name)
        #     verification = verify_data_dictionary(df, yaml_file)
        #     if verification:
        #         for k,v in verification.items():
        #             if not v:
        #                 raise Exception("{} is not true".format(k))
        #     else:
        #         print("WARNING: {} does not contain data dictionary".format(notebook))

    except UnknownBook:
        logger.info("Book has not been pushed yet")
        return

    if shelf.is_available(name=target_book.name, version=target_book.version):
        existing_book = shelf.load(
            name=target_book.name,
            version=target_book.version,
            edition=target_book.edition,
            force=False,
        )
        logger.info(f"Remote book exists. Expecting hash: {existing_book.hash()}")
        # import pdb; pdb.set_trace()
        if existing_book.edition != target_book.edition:
            raise ValueError(
                "Edition of calculated book doesn't match the remote bookshelf "
                f"({target_book.edition} != {existing_book.edition})"
            )

        if existing_book.hash() != target_book.hash():
            raise ValueError(
                "Hash of calculated book doesn't match the remote bookshelf "
                f"({target_book.hash()} != {existing_book.hash()})"
            )
    else:
        logger.info("Matching book version does not exist on remote bookshelf")
