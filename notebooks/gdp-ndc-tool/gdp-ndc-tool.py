# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -pycharm
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.15.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # gdp-ndc-tool
#
# We use the GDP results from the Excel NDC tool version 13Mar23a_CR
# They can't be downloaded anywhere, so we just have a CSV here

# %%
import logging
import tempfile

import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %% [markdown]
# # Initialise

# %%
logging.basicConfig(level=logging.INFO)

# %%
metadata = load_nb_metadata("gdp-ndc-tool")
metadata.dict()

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()

# %%
local_bookshelf

# %% [markdown]
# # Fetch

# %%
csv_fname = metadata.download_file()

# %%
sr = scmdata.ScmRun(csv_fname)
sr

# %% [markdown]
# # Process

# %%
sr["model"] = "NDC Tool"

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("gdp", sr)

# %%
book.metadata()

# %% [markdown]
# This notebook is not responsible for uploading the book to the `BookShelf`.
# See docs for how to upload `Books` to the `BookShelf`

# %%
