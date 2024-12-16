"""Functionality for interacting with and visualising the structure of a dataset."""

from __future__ import annotations

from collections.abc import Iterable

import attrs
from scmdata import ScmRun

from bookshelf.schema import NotebookMetadata


@attrs.define
class VerificationInfo:
    """
    Result from the data verification process.
    """

    column_match: bool = attrs.field(init=False, default=True)
    col_type_match: bool = attrs.field(init=False, default=True)
    controlled_vocabulary_match: bool = attrs.field(init=False, default=True)
    non_na_col_match: bool = attrs.field(init=False, default=True)

    def error_message(self) -> str | None:
        """
        Check if the data dictionary matches the data.

        Returns
        -------
        :
            A string message indicating the result of the verification if it fails.
            Otherwise None
        """
        validation = attrs.asdict(self, recurse=False)
        for attr, value in validation.items():
            if not value:
                return f"Data dictionary does not match the data: {attr} is not true"

        return None


def get_dataset_dictionary(data: ScmRun) -> dict[str, Iterable[str | float | int]]:
    """
    Extract unique metadata values from an ScmRun object.

    This function iterates through the columns of the metadata in the ScmRun object
    and creates a dictionary. Each key in the dictionary corresponds to a column name,
    and the associated value is a list of unique values in that column.

    Parameters
    ----------
    data
        The input ScmRun object from which metadata will be extracted.

    Returns
    -------
    :
        A dictionary with column names as keys and lists of unique values in those
        columns as values. The values are extracted from the metadata of the ScmRun object.
    """
    data_dict: dict[str, Iterable[str | int | float]] = {}
    for column in data.meta_attributes:
        data_dict[column] = data.get_unique_meta(column)

    return data_dict


def print_dataset_structure(data: ScmRun) -> None:
    """
    Print the structure of a dataset.

    This function displays a tabular representation of the dataset's dimensions
    and their unique values. Each row corresponds to a unique value in a dimension,
    and each column represents a different dimension of the dataset.

    Parameters
    ----------
    data
        The input dataset in the form of an ScmRun object.

    Returns
    -------
    :
        This function does not return anything. It prints the dataset structure
        directly to the console.
    """
    data_dict = get_dataset_dictionary(data)

    # Convert values to strings once
    k_lst = list(data_dict.keys())
    v_lst = [list(map(str, values)) for values in data_dict.values()]
    max_length = max(len(values) for values in v_lst)

    # Calculate width for each column
    width_lst = [max(len(str(item)) for item in [key, *values]) + 5 for key, values in zip(k_lst, v_lst)]

    # Print header
    print("".join(f"{item:{width}}" for item, width in zip(k_lst, width_lst)))

    # Print header divider
    print(
        "".join(
            f"{item:{width}}" for item, width in zip(["-" * (width - 5) for width in width_lst], width_lst)
        )
    )

    # Print each row of values
    for i in range(max_length):
        row_values = [values[i] if i < len(values) else "" for values in v_lst]
        print("".join(f"{item:{width}}" for item, width in zip(row_values, width_lst)))


def verify_data_dictionary(data: ScmRun, notebook_config: NotebookMetadata) -> VerificationInfo | None:
    """
    Verify the consistency of data against the specifications in a notebook's data dictionary.

    This function checks various aspects of data integrity, including column matching,
    data type consistency, adherence to controlled vocabularies,
    and the presence of required fields without missing (NA) values.
    It performs these checks by comparing the actual data with the requirements
    specified in the data dictionary of the notebook configuration.

    Parameters
    ----------
    data: ScmRun
        The data set to be verified.
    notebook_config: NotebookMetadata
        Configuration of the notebook, including the data dictionary which contains specifications
        for data validation.

    Returns
    -------
    :
        An instance of VerificationInfo that contains the results of the data verification.

        If the data dictionary is empty, the function returns None,
        indicating that no verification is necessary.
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
                data.meta[variable.name].astype(variable.type)  # type: ignore
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
