# %%
"""
Dataset structure

This module offers some functions to display the structure of a dataset
"""


# %%
from scmdata import ScmRun


# %%
def get_dataset_dictionary(data: ScmRun) -> dict:
    """
    Extract unique metadata values from an ScmRun object.

    This function iterates through the columns of the metadata in the ScmRun object
    and creates a dictionary. Each key in the dictionary corresponds to a column name,
    and the associated value is a list of unique values in that column.

    Parameters
    ----------
    data: ScmRun
        The input ScmRun object from which metadata will be extracted.

    Returns
    -------
    dict
        A dictionary with column names as keys and lists of unique values in those
        columns as values. The values are extracted from the metadata of the ScmRun object.
    """
    data_dict = {}
    for column in data.meta.columns:
        data_dict[column] = data.get_unique_meta(column)

    return data_dict


# %%
def get_dataset_structure(data: ScmRun) -> None:
    """
    Print the structure of a dataset.

    This function displays a tabular representation of the dataset's dimensions
    and their unique values. Each row corresponds to a unique value in a dimension,
    and each column represents a different dimension of the dataset.

    Parameters
    ----------
    data: ScmRun
        The input dataset in the form of an ScmRun object.

    Returns
    -------
    None
        This function does not return anything. It prints the dataset structure
        directly to the console.
    """
    data_dict = get_dataset_dictionary(data)

    # Convert values to strings once
    k_lst = list(data_dict.keys())
    v_lst = [list(map(str, values)) for values in data_dict.values()]
    max_length = max(len(values) for values in v_lst)

    # Calculate width for each column
    width_lst = [
        max(len(str(item)) for item in [key, *values]) + 5 for key, values in zip(k_lst, v_lst)
    ]

    # Print header
    print("".join(f"{item:{width}}" for item, width in zip(k_lst, width_lst)))

    # Print each row of values
    for i in range(max_length):
        row_values = [values[i] if i < len(values) else "" for values in v_lst]
        print("".join(f"{item:{width}}" for item, width in zip(row_values, width_lst)))
