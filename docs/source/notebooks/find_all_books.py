# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Finding the available books
#
# The `bookshelf` library hosts a multitude of volumes, each with various
# versions or books. Below is a guide to discovering all available books.

# %% [markdown]
# ## Finding all available volumes and versions
#
# To enumerate all volumes along with their versions, you can leverage the
# `find_notebooks` function in `test_notebooks`. But This function would not
# be available if you install bookshelf via pypl


# %%
import sys

from bookshelf.constants import ROOT_DIR

DIR = ROOT_DIR + "/tests/notebooks"
sys.path.insert(1, DIR)
import test_notebooks

books_info = test_notebooks.find_notebooks()

books_info_dict = dict()
for path, volume, version in books_info:
    books_info_dict.setdefault(volume, []).append(version)

books_info_dict


# %% [markdown]
#
# This method provides a comprehensive list of all available volumes along with their versions
# from local directory, facilitating easy access and management of the books within the bookshelf.

# %% [markdown]
# ## Finding all available books of a specific volume
#
# Should your interest lie in a particular volume, and you wish to explore all its available books
# in remote bookshelf, the `list_versions` function provided by `BookShelf` offers a
# straightforward solution.

# %%
from bookshelf import BookShelf

shelf = BookShelf()

volume = "rcmip-emissions"
shelf.list_versions(volume)
