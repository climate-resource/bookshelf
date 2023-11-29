import pandas as pd
import pytest
from scmdata import ScmRun

from bookshelf.dataset_structure import get_dataset_dictionary, get_dataset_structure


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


def test_get_dataset_structure(sample_scmrun, capsys):
    # Call the function which will print to the console
    get_dataset_structure(sample_scmrun)

    # Capture the output from stdout and stderr
    captured = capsys.readouterr()

    expected_output = (
        "model      region          scenario     unit            variable        \n"
        "model1     unspecified     rcp26        unspecified     unspecified     \n"
        "model2                                                                  \n"
        "model3                                                                  \n"
    )

    # Clean up whitespace for accurate comparison
    captured_output = captured.out.strip()
    expected_output = expected_output.strip()

    # Assert that the captured output matches the expected format
    assert (
        captured_output == expected_output
    ), "The output format does not match the expected format."
