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
# To enumerate all volumes along with their versions, begin by identifying
# the root directory where the notebooks generating these books are located,
# accessible via the `NOTEBOOK_DIRECTORY`. Subsequently, leverage the
# `get_available_versions` function to ascertain all versions for each volume
# from local directory.


# %%
import os
from glob import glob

from bookshelf.notebook import (
    get_available_versions,
    get_notebook_directory,
)

NOTEBOOK_DIRECTORY = get_notebook_directory()
notebooks = glob(os.path.join(NOTEBOOK_DIRECTORY, "**", "*.py"), recursive=True)

books_info = []
for nb in notebooks:
    versions = get_available_versions(nb.replace(".py", ".yaml"), include_private=False)
    notebook_name = os.path.basename(nb)[:-3]
    books_info.extend((nb, notebook_name, v) for v in versions)

books_info

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
