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

import tempfile

import dotenv
import pooch
import scmdata

from bookshelf import BookShelf, LocalBook
from bookshelf.constants import PROCESSED_DATA_DIR

# %%
dotenv.load_dotenv()

# %% tags=["parameters"]
BOOK_VERSION = "v0.0.1"
DATASET_VERSION = "v5.1.0"
PROCESSING_DIR = PROCESSED_DATA_DIR

# %%
book = LocalBook.create_new(
    "rcmip-emissions", version=BOOK_VERSION, local_bookshelf=PROCESSING_DIR
)

# %% [markdown]
# #  Fetch

# %%
rcmip_fname = pooch.retrieve(
    "https://rcmip-protocols-au.s3-ap-southeast-2.amazonaws.com/v5.1.0/rcmip-emissions-annual-means-v5-1-0.csv",
    known_hash="2af9f90c42f9baa813199a902cdd83513fff157a0f96e1d1e6c48b58ffb8b0c1",
)

# %%
rcmip_emissions = scmdata.ScmRun(rcmip_fname, lowercase_cols=True)
rcmip_emissions

# %% [markdown]
# # Process

# %%
book.add_timeseries("complete", rcmip_emissions)


# %%

# %%
book.metadata().to_json()

# %%
shelf = BookShelf()

shelf.save(book)

# %%
temp_bookshelf_dir = tempfile.mkdtemp()
temp_shelf = BookShelf(path=temp_bookshelf_dir)

# %%
temp_shelf.load("rcmip-emissions")

# %%
