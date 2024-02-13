import logging
import os
import sys
import tempfile
from glob import glob
from typing import Optional

import attrs
import pytest
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
notebooks_lst = []


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


@attrs.define
class VerificationInfo:
    column_match: bool = attrs.field(init=False, default=True)
    col_type_match: bool = attrs.field(init=False, default=True)
    controlled_vocabulary_match: bool = attrs.field(init=False, default=True)
    non_na_col_match: bool = attrs.field(init=False, default=True)

    def is_valid(self) -> tuple[bool, str]:
        validation = attrs.asdict(self, recurse=False)
        for attr, value in validation.items():
            if not value:
                return (
                    False,
                    f"Data dictionary does not match the data: {attr} is not true",
                )
        return True, ""


def verify_data_dictionary(data: ScmRun, notebook_config: NotebookMetadata) -> Optional[VerificationInfo]:
    """
     Verifies the consistency of data against the specifications in a notebook's data dictionary.

     This function checks various aspects of data integrity, including column matching,
     data type consistency, adherence to controlled vocabularies, and the presence of required
     fields without missing (NA) values. It performs these checks by comparing the actual data
     with the requirements specified in the data dictionary of the notebook configuration.

     Parameters
     ----------
     data: ScmRun
         The data set to be verified.
     notebook_config: NotebookMetadata
         Configuration of the notebook, including the data dictionary which contains specifications
         for data validation.

     Returns:
    :Optional[class:`VerificationInfo`]: An instance of VerificationInfo that contains the results of the
         data verification. If the data dictionary is empty, the function returns None, indicating
         that no verification is necessary.
    """

    # Return None if the notebook's data dictionary is empty, indicating no verification needed.
    if len(notebook_config.data_dictionary) == 0:
        return None

    verification_info = VerificationInfo()

    # Retrieve unique metadata values from the data for comparison with the data dictionary.
    unique_values = get_dataset_dictionary(data)

    # Iterate through each entry (dimension) in the data dictionary.
    for variable in notebook_config.data_dictionary:
        # Check if the required dimension in the data dictionary not in the data.
        if variable.name not in data.meta.columns:
            if variable.required_column is True:
                verification_info.column_match = False
            else:
                continue
        else:
            # Validate that the data type of the column in the data matches its specified type
            # in the data dictionary.
            try:
                data.meta[variable.name].astype(variable.type)
            except ValueError:
                verification_info.col_type_match = False

            # If a controlled vocabulary (CV) is defined, check if all data values are included in the CV.
            if variable.controlled_vocabulary is not None:
                if not set(unique_values[variable.name]).issubset(
                    set(
                        [
                            controlled_vocabulary.value
                            for controlled_vocabulary in variable.controlled_vocabulary
                        ]
                    )
                ):
                    verification_info.controlled_vocabulary_match = False

            # For not allowed missing value(NA) dimensions, verify there are NA values in the data.
            if variable.allowed_NA is False:
                if data.meta[variable.name].isna().any():
                    verification_info.non_na_col_match = False
    return verification_info


def test_verify_data_dictionary():
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
                "allowed_NA": True,
                "required_column": True,
            },
            {
                "name": "region",
                "description": "Area that the results are valid for",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
                "controlled_vocabulary": [
                    {"value": "World", "description": "Aggregate results for the world"}
                ],
            },
            {
                "name": "scenario",
                "description": "scenario",
                "type": "string",
                "allowed_NA": True,
                "required_column": True,
            },
            {
                "name": "unit",
                "description": "Unit of the timeseries",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
            {
                "name": "variable",
                "description": "Variable name",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
        ],
    )

    verification = verify_data_dictionary(data, config)

    assert verification.is_valid()


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
                "allowed_NA": True,
                "required_column": True,
            },
            # no "source" exist in data
            {
                "name": "source",
                "description": "Name of the dataset",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
            {
                "name": "region",
                "description": "Area that the results are valid for",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
                "controlled_vocabulary": [
                    {"value": "World", "description": "Aggregate results for the world"}
                ],
            },
            {
                "name": "scenario",
                "description": "scenario",
                "type": "string",
                "allowed_NA": True,
                "required_column": True,
            },
            {
                "name": "unit",
                "description": "Unit of the timeseries",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
            {
                "name": "variable",
                "description": "Variable name",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
        ],
    )

    verification = verify_data_dictionary(data, config)

    assert not verification.column_match


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
                "allowed_NA": True,
                "required_column": True,
            },
            {
                "name": "region",
                "description": "Area that the results are valid for",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
                "controlled_vocabulary": [
                    {"value": "World", "description": "Aggregate results for the world"}
                ],
            },
            {
                "name": "scenario",
                "description": "scenario",
                "type": "string",
                "allowed_NA": True,
                "required_column": True,
            },
            {
                "name": "unit",
                "description": "Unit of the timeseries",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
            {
                "name": "variable",
                "description": "Variable name",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
        ],
    )

    verification = verify_data_dictionary(data, config)

    assert not verification.col_type_match


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
                "allowed_NA": True,
                "required_column": True,
            },
            {
                "name": "region",
                "description": "Area that the results are valid for",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
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
                "allowed_NA": True,
                "required_column": True,
            },
            {
                "name": "unit",
                "description": "Unit of the timeseries",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
            {
                "name": "variable",
                "description": "Variable name",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
        ],
    )

    verification = verify_data_dictionary(data, config)

    assert not verification.controlled_vocabulary_match


def test_verify_data_dictionary_non_na_col_match():
    # If required is set, are there any missing values

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
                "allowed_NA": True,
                "required_column": True,
            },
            {
                "name": "region",
                "description": "Area that the results are valid for",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
                "controlled_vocabulary": [
                    {"value": "World", "description": "Aggregate results for the world"}
                ],
            },
            {
                "name": "scenario",
                "description": "scenario",
                "type": "string",
                "allowed_NA": True,
                "required_column": True,
            },
            {
                "name": "unit",
                "description": "Unit of the timeseries",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
            {
                "name": "variable",
                "description": "Variable name",
                "type": "string",
                "allowed_NA": False,
                "required_column": True,
            },
        ],
    )

    verification = verify_data_dictionary(data, config)

    assert not verification.non_na_col_match


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
            if name.split("_")[-1] == "long":
                continue
            data = target_book.timeseries(name)  # error occurs
            verification = verify_data_dictionary(data, nb_metadata)

            if verification:
                is_valid, error_message = verification.is_valid()
                if not is_valid:
                    pytest.xfail(error_message)
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
