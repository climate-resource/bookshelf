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
