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

import pooch
import scmdata

from bookshelf import Book
from bookshelf.constants import PROCESSED_DATA_DIR


# %% tags=["parameters"]
BOOK_VERSION = "v0.1.0"
DATASET_VERSION = ""
PROCESSING_DIR = PROCESSED_DATA_DIR

# %%
book = Book.create_new("rcmip-emissions", version=BOOK_VERSION, local_bookshelf=PROCESSING_DIR)

# %% [markdown]
# #  Fetch

# %%
rcmip_fname = pooch.retrieve(
    "https://rcmip-protocols-au.s3-ap-southeast-2.amazonaws.com/v5.1.0/rcmip-emissions-annual-means-v5-1-0.csv", 
    known_hash=None
)

# %%
rcmip_emissions = scmdata.ScmRun(rcmip_fname, lowercase_cols=True)
rcmip_emissions

# %% [markdown]
# # Process

# %%
book.add_timeseries("complete", rcmip_emissions)


# %%
book.metadata().to_json()

# %%
book_2 = Book("rcmip-emissions", DATASET_VERSION)

# %%
book_2.metadata()

# %%
