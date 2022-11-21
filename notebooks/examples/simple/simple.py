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

# %% [markdown]
# # Example
#
# This notebook is an example for the creation of a new book and can be used as a template.
#
# In this example, we fetch the RCMIP Radiative Forcing timeseries from `rcmip.org` and
# produce a resource that contains a filtered subset of variables.

# %%
import logging
import tempfile

import scmdata

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

# %% [markdown]
# # Initialise

# %%
logging.basicConfig(level=logging.INFO)

# %%
metadata = load_nb_metadata("examples/simple")
metadata.dict()

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()

# %%
local_bookshelf

# %% [markdown]
# # Fetch

# %% [markdown]
# We recommend using `pooch` to download input data. `Pooch` will verify that the
# downloaded file matches the expected hash as a check that the download was performed
# successfully.

# %%
data_fname = metadata.download_file()
data = scmdata.ScmRun(data_fname, lowercase_cols=True)
data.head()

# %% [markdown]
# # Process

# %%
data.get_unique_meta("variable")

# %%
rf = data.filter(
    variable=["Radiative Forcing|Anthropogenic", "Radiative Forcing|Natural"]
)
rf

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %% [markdown]
# Create a new `Resource` in the `Book` using the RF `scmdata.ScmRun` object. This function copies the timeseries to a local file and calculate the hash of this file. This hash can be used to check if the files have been modified.

# %%
book.add_timeseries("rf", rf)

# %% [markdown]
# Below the `Book`'s metadata is shown. This contains all of the metadata about the `Book` and the associated `Resources`.
#
# This is the metadata that clients download and can be used to fetch the `Book`'s `Resources`. Once deployed this `Book` becomes immutable. Any changes to the metadata or data requires releasing a new version of a `Book`.

# %%
book.metadata()

# %% [markdown]
# That is all.
#
# This notebook is not responsible for uploading the book to the `BookShelf`. See docs for how to upload `Books` to the `BookShelf`

# %%
