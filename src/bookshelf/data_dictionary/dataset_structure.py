# %%
"""
Dataset structure

This module offers a function to display the structure of a dataset
"""


# %%
import numpy as np
from scmdata import ScmRun


# %%
def get_dataset_structure(data: ScmRun) -> None:
    """
    Display structure of a dataset

    This function print all the dimension and unique values for each dimension

    Parameters
    ----------
    data:ScmRun
        The input dataset

    Returns
    -------
    :str
        all the dimension and unqiue values for each dimension in a form of a table
    """
    data_dict = {}
    for column in data.meta.columns:
        data_dict[column] = data.get_unique_meta(column)

    k_lst = list(data_dict.keys())
    v_lst = list(data_dict.values())
    max_v_lst = max(v_lst, key=len)
    max_length = len(max_v_lst)

    # Determine the space for each column
    width_lst = []
    for value in v_lst:
        v = np.array(value).astype(str)
        width = len(sorted(v, key=len, reverse=True)[0]) + 5
        width_lst.append(width)

    # print header
    header = ""
    for i in range(len(width_lst) - 1):
        header += "{:<{width}}".format(k_lst[i], width=width_lst[i])
    print(header)

    # print unique values in each dimension
    maxIndex = max_length - 1
    index = 0
    while index <= maxIndex:
        row_str = " "
        for i in range(len(v_lst) - 1):
            v = np.array(v_lst[i]).astype(str)
            width = len(sorted(v, key=len, reverse=True)[0]) + 5
            if index < len(v_lst[i]):
                row_str += "{:<{width}}".format(v_lst[i][index], width=width_lst[i])
            else:
                row_str += "{:<{width}}".format(" ", width=width_lst[i])
        index += 1
        print(row_str)
