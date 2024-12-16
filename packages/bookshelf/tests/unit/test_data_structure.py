import pandas as pd
import pytest
from scmdata import ScmRun
from scmdata.testing import get_single_ts

from bookshelf.dataset_structure import (
    get_dataset_dictionary,
    print_dataset_structure,
    verify_data_dictionary,
)
from bookshelf.schema import NotebookMetadata


# Fixture for creating a sample ScmRun object
@pytest.fixture
def sample_scmrun():
    df_dict = {
        "scenario": ["rcp26", "rcp26", "rcp26"],
        "model": ["model1", "model2", "model3"],
        "region": ["unspecified", "unspecified", "unspecified"],
        "variable": ["unspecified", "unspecified", "unspecified"],
        "unit": ["unspecified", "unspecified", "unspecified"],
        "1980": ["1", "2", "3"],
        "1981": ["2", "3", "4"],
    }
    sample_df = pd.DataFrame(df_dict)
    df_ScmRun = ScmRun(sample_df)
    return df_ScmRun


def test_get_dataset_dictionary(sample_scmrun):
    expected_dict = {
        "model": ["model1", "model2", "model3"],
        "region": ["unspecified"],
        "scenario": ["rcp26"],
        "unit": ["unspecified"],
        "variable": ["unspecified"],
    }

    result_dict = get_dataset_dictionary(sample_scmrun)
    assert result_dict == expected_dict, "Dictionary output does not match expected format."


def test_print_dataset_structure(sample_scmrun, capsys):
    # Call the function which will print to the console
    print_dataset_structure(sample_scmrun)

    # Capture the output from stdout and stderr
    captured = capsys.readouterr()

    expected_output = (
        "model      region          scenario     unit            variable        \n"
        "------     -----------     --------     -----------     -----------     \n"
        "model1     unspecified     rcp26        unspecified     unspecified     \n"
        "model2                                                                  \n"
        "model3                                                                  \n"
    )

    # Clean up whitespace for accurate comparison
    captured_output = captured.out.strip()
    expected_output = expected_output.strip()

    # Assert that the captured output matches the expected format
    assert captured_output == expected_output, "The output format does not match the expected format."


def test_verify_data_dictionary():
    data = get_single_ts()

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

    assert verification.error_message() is None


def test_verify_data_dictionary_col_name_match():
    # Are all the columns in the data dictionary

    data = get_single_ts()

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

    data = get_single_ts()

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

    data = get_single_ts()

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

    data = get_single_ts()
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
