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
# # PRIMAP-hist
#

# %%
import logging
import tempfile

import pandas as pd
import pooch
import scmdata

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

# %% [markdown]
# # Initialise

# %%
logging.basicConfig(level=logging.INFO)

# %%
metadata = load_nb_metadata("primap-hist")
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
data_fname = pooch.retrieve(
    url="https://zenodo.org/record/5494497/files/Guetschow-et-al-2021-PRIMAP-hist_v2.3.1_20-Sep_2021.csv?download=1",
    known_hash="ef53000db17dc2bac6f77eeb302763a1e99b2654f17108fe8ea3280fe55f8eb9",
)

data_df = pd.read_csv(data_fname)
data_df

# %%
col_renames = {
    "scenario (PRIMAP-hist)": "scenario",
    "entity": "variable",
    "area (ISO3)": "region",
    "category (IPCC2006_PRIMAP)": "category",
}
data_df_renamed = data_df.rename(col_renames, axis=1)
data_df_renamed["model"] = "PRIMAP-hist"
data_df_renamed["variable"] = "Emissions|" + data_df_renamed["variable"]

# %%
data = scmdata.ScmRun(data_df_renamed, lowercase_cols=True)
data.head()

# %% [markdown]
# # Process

# %%
data.get_unique_meta("variable")

# %%
len(data.get_unique_meta("region"))

# %%
book = LocalBook.create_new(
    name=metadata.name, version=metadata.version, local_bookshelf=local_bookshelf
)

# %%
book.add_timeseries("clean", data)

# %%
book.metadata().descriptor

# %% [markdown]
# That is all.
#
# This notebook is not responsible for uploading the book to the `BookShelf`. See docs for how to upload `Books` to the `BookShelf`

# %%
