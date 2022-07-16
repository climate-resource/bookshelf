# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -pycharm
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import os
from bookshelf import Book
from bookshelf.constants import PROCESSED_DATA_DIR


# %% tags=["parameters"]
BOOK_VERSION = "v0.1.0"
DATASET_VERSION = ""
PROCESSING_DIR = PROCESSED_DATA_DIR

# %%
book = Book("rcmip-emissions", version=BOOK_VERSION, local_bookshelf=PROCESSING_DIR)

# %% [markdown]
# #  Fetch

# %%
pooch.retrieve()

# %% [markdown]
# # Process

# %%

# %%
book.add_timeseries("complete")


# %%
book.metadata()
