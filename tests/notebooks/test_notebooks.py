import logging
import os
import sys
import tempfile
from glob import glob

import pytest
from attrs import define, field
from scmdata import ScmRun, testing

from bookshelf import BookShelf
from bookshelf.dataset_structure import get_dataset_dictionary
from bookshelf.errors import UnknownBook
from bookshelf.notebook import (
    get_available_versions,
    get_notebook_directory,
    load_nb_metadata,
    run_notebook,
)
from bookshelf.schema import NotebookMetadata

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


@define
class verification:
    col_name_match: bool = field(init=False, default=True)
    col_type_match: bool = field(init=False, default=True)
    controlled_vocabulary_match: bool = field(init=False, default=True)
    non_na_col_match: bool = field(init=False, default=True)


def verify_data_dictionary(data: ScmRun, notebook_config: NotebookMetadata) -> verification:
    verificat = verification()
    if len(notebook_config.data_dictionary) == 0:
        return None

    unique_values = get_dataset_dictionary(data)
    for variable in notebook_config.data_dictionary:
        if variable.name not in data.meta.columns:
            verificat.col_name_match = False
        else:
            try:
                data.meta[variable.name].astype(variable.type)
            except ValueError:
                verificat.col_type_match = False
            if variable.controlled_vocabulary is not None:
                if not set(unique_values[variable.name]).issubset(
                    set(
                        [
                            controlled_vocabulary.value
                            for controlled_vocabulary in variable.controlled_vocabulary
                        ]
                    )
                ):
                    verificat.controlled_vocabulary_match = False
            if variable.required is True:
                if data.meta[variable.name].isna().any():
                    verificat.non_na_col_match = False
    return verificat


def test_verify_data_dictionary_col_name_macth():
    # Are all the columns in the data dictionary

    data = testing.get_single_ts()

    config = NotebookMetadata(
        name="test",
        version="v1.0.0",
        edition=1,
        license="unspecified",
        source_file="",
        private=False,
        metadata={},
        dataset={
            "author": "test",
            "files": [],
        },
        data_dictionary=[
            {
                "name": "model",
                "description": "The IAM that was used to create the scenario",
                "type": "string",
                "required": False,
            },
            # no "source" exist in data
            {
                "name": "source",
                "description": "Name of the dataset",
                "type": "string",
                "required": True,
            },
            {
                "name": "region",
                "description": "Area that the results are valid for",
                "type": "string",
                "required": True,
                "controlled_vocabulary": [
                    {"value": "World", "description": "Aggregate results for the world"}
                ],
            },
            {
                "name": "scenario",
                "description": "scenario",
                "type": "string",
                "required": False,
            },
            {
                "name": "unit",
                "description": "Unit of the timeseries",
                "type": "string",
                "required": True,
            },
            {
                "name": "variable",
                "description": "Variable name",
                "type": "string",
                "required": True,
            },
        ],
    )

    verification = verify_data_dictionary(data, config)

    expected_columns = {entry.name for entry in config.data_dictionary}
    actual_columns = set(data.meta.columns)
    expected_result = expected_columns.issubset(actual_columns)
    assert verification.col_name_match == expected_result


def test_verify_data_dictionary_col_type_match():
    # Is the type of a column correct

    data = testing.get_single_ts()

    config = NotebookMetadata(
        name="test",
        version="v1.0.0",
        edition=1,
        license="unspecified",
        source_file="",
        private=False,
        metadata={},
        dataset={
            "author": "test",
            "files": [],
        },
        data_dictionary=[
            {
                "name": "model",
                "description": "The IAM that was used to create the scenario",
                # type == "int" rather than "string"
                "type": "int",
                "required": False,
            },
            {
                "name": "region",
                "description": "Area that the results are valid for",
                "type": "string",
                "required": True,
                "controlled_vocabulary": [
                    {"value": "World", "description": "Aggregate results for the world"}
                ],
            },
            {
                "name": "scenario",
                "description": "scenario",
                "type": "string",
                "required": False,
            },
            {
                "name": "unit",
                "description": "Unit of the timeseries",
                "type": "string",
                "required": True,
            },
            {
                "name": "variable",
                "description": "Variable name",
                "type": "string",
                "required": True,
            },
        ],
    )

    verification = verify_data_dictionary(data, config)

    type_mismatch = False
    for entry in config.data_dictionary:
        column_name = entry.name
        expected_type = entry.type
        if column_name in data.meta.columns:
            try:
                data.meta[column_name].astype(expected_type)
                type_mismatch = False
            except ValueError:
                type_mismatch = True
                break

    assert verification.col_type_match != type_mismatch


def test_verify_data_dictionary_controlled_vocabulary_match():
    # If a CV is present, are there any values not in the CV

    data = testing.get_single_ts()

    config = NotebookMetadata(
        name="test",
        version="v1.0.0",
        edition=1,
        license="unspecified",
        source_file="",
        private=False,
        metadata={},
        dataset={
            "author": "test",
            "files": [],
        },
        data_dictionary=[
            {
                "name": "model",
                "description": "The IAM that was used to create the scenario",
                "type": "int",
                "required": False,
            },
            {
                "name": "region",
                "description": "Area that the results are valid for",
                "type": "string",
                "required": True,
                "controlled_vocabulary": [
                    {
                        # "World" is a value in region column in data, which is not a subset of ["Test"]
                        "value": "Test",
                        "description": "Aggregate results for the world",
                    }
                ],
            },
            {
                "name": "scenario",
                "description": "scenario",
                "type": "string",
                "required": False,
            },
            {
                "name": "unit",
                "description": "Unit of the timeseries",
                "type": "string",
                "required": True,
            },
            {
                "name": "variable",
                "description": "Variable name",
                "type": "string",
                "required": True,
            },
        ],
    )

    verification = verify_data_dictionary(data, config)

    cv_mismatch = False
    for entry in config.data_dictionary:
        column_name = entry.name
        if entry.controlled_vocabulary is not None and column_name in data.meta.columns:
            allowed_values = {cv.value for cv in entry.controlled_vocabulary}
            actual_values = set(data.meta[column_name].dropna().unique())
            if not actual_values.issubset(allowed_values):
                cv_mismatch = True
                break

    assert verification.controlled_vocabulary_match != cv_mismatch


def test_verify_data_dictionary_non_na_col_match():
    # If a CV is present, are there any values not in the CV

    data = testing.get_single_ts()
    # unit column with missing value
    data["unit"] = None

    config = NotebookMetadata(
        name="test",
        version="v1.0.0",
        edition=1,
        license="unspecified",
        source_file="",
        private=False,
        metadata={},
        dataset={
            "author": "test",
            "files": [],
        },
        data_dictionary=[
            {
                "name": "model",
                "description": "The IAM that was used to create the scenario",
                "type": "int",
                "required": False,
            },
            {
                "name": "region",
                "description": "Area that the results are valid for",
                "type": "string",
                "required": True,
                "controlled_vocabulary": [
                    {"value": "World", "description": "Aggregate results for the world"}
                ],
            },
            {
                "name": "scenario",
                "description": "scenario",
                "type": "string",
                "required": False,
            },
            {
                "name": "unit",
                "description": "Unit of the timeseries",
                "type": "string",
                "required": True,
            },
            {
                "name": "variable",
                "description": "Variable name",
                "type": "string",
                "required": True,
            },
        ],
    )

    verification = verify_data_dictionary(data, config)

    non_na_mismatch = False
    for entry in config.data_dictionary:
        column_name = entry.name
        if entry.required is True and column_name in data.meta.columns:
            if data.meta[column_name].isna().any():
                non_na_mismatch = True
                break

    assert verification.non_na_col_match != non_na_mismatch


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
        files_names = [i["name"] for i in target_book.metadata()["resources"]]

        for name in files_names:
            data = target_book.timeseries(name)
            verification = verify_data_dictionary(data, nb_metadata)

            if verification:
                for attr in dir(verification):
                    if not attr.startswith("__"):
                        result = getattr(verification, attr)
                        if not result:
                            pytest.xfail(
                                f"Data dictionary does not match the data: {attr} is not true"
                            )
            else:
                logger.warning(f"{notebook} does not contain data dictionary")

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

        if existing_book.hash() != target_book.hash():
            raise ValueError(
                "Hash of calculated book doesn't match the remote bookshelf "
                f"({target_book.hash()} != {existing_book.hash()})"
            )
    else:
        logger.info("Matching book version does not exist on remote bookshelf")
