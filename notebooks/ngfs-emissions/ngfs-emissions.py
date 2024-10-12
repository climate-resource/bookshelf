# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -pycharm
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.1
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # PRIMAP-hist
#
# The PRIMAP-hist dataset of historical GHG emissions.

# %%
# Need to think about how to handle notebook dependencies
# !pip install "pyam-iamc>=2"

# %%
import logging
import re
import tempfile

import pyam
import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %%
pyam.__version__

# %% [markdown]
# # Initialise

# %%
logging.basicConfig(level=logging.INFO)

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()
version = "v3.4"

# %%
metadata = load_nb_metadata("ngfs-emissions", version=version)
dict(metadata)


# %% [markdown]
# # Fetch

# %% [markdown]
# We are using `pyam`s downloading functionality.

# %%
df = pyam.read_iiasa(f'ngfs_phase_{version.split(".")[0][1:]}', variable="Emissions|*")

# %%
df

# %%
df.model

# %%
df.scenario

# %%
df.unit

# %%
df.filter(region="GCAM 5.3+ NGFS|South Asia", variable="Emissions|CO2").timeseries()

# %%

# %%
data = scmdata.ScmRun(df, lowercase_cols=True)
data.head()


# %% [markdown]
# # Process
#
# Minor renames and enrichment


# %%
data.get_unique_meta("scenario")

# %%
data["scenario"] = data["scenario"].str.replace("Below 2?C", "Below 2°C")

# %%
# TODO: the data does not indicate the GHG metric used for calculating CO2 equivalent units.
# For many applications, you would need to add this information.

# %%
data.get_unique_meta("unit")

# %%
data["unit"] = data["unit"].str.replace("-equiv", "")

# %%
data.get_unique_meta("unit")

# %%
data.get_unique_meta("variable")

# %%
data["variable"] = data["variable"].str.replace("Kyoto Gases", "Total GHG")
data.get_unique_meta("variable")

# %%
data.head()

# %%
data.get_unique_meta("model")

# %%
downscaled_models = [re.escape(m) for m in data.get_unique_meta("model") if m.startswith("Downscaling ")]
downscaled_models

# %%
data_downscaled = data.filter(model=downscaled_models, regexp=True)
data_direct = data.filter(model=downscaled_models, regexp=True, keep=False)

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("downscaled", data_downscaled)
book.add_timeseries("iam_results", data_direct)

# %%
book.metadata()

# %% [markdown]
# This notebook is not responsible for uploading the book to the `BookShelf`. See docs for how to upload
# `Books` to the `BookShelf`

# %%
