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
# # Worldbank Data Indicators
#

# %%
import logging
import tempfile

import pandas as pd
import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %% [markdown]
# # Initialise

# %%
logging.basicConfig(level=logging.INFO)

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()
version = "v5.1.0.0"

# %%
metadata = load_nb_metadata("hadcrut", version=version)
metadata.model_dump()

# %%
local_bookshelf

# %% [markdown]
# # Fetch

# %%
data_monthly = metadata.download_file(0)
data_annual = metadata.download_file(1)

# %%
df_monthly = pd.read_csv(data_monthly, index_col=0)
df_annual = pd.read_csv(data_annual, index_col=0)

# %%
column_rename = {
    "Anomaly (deg C)": "Temperature|Anomaly|Mean",
    "Lower confidence limit (2.5%)": "Temperature|Anomaly|Lower confidence limit (2.5%)",
    "Upper confidence limit (97.5%)": "Temperature|Anomaly|Upper confidence limit (97.5%)",
}
df_monthly = df_monthly.rename(column_rename, axis=1).T
df_annual = df_annual.rename(column_rename, axis=1).T
for df in [df_monthly, df_annual]:
    df.index.name = "variable"
    df["scenario"] = "historical"
    df["model"] = "CRUTEM5+HadSST4"
    df["source"] = f"HadCRUT @ {metadata.version}"
    df["unit"] = "deg C"
    df["region"] = "Global"
df_monthly

# %%
scmdata.ScmRun(df_monthly).timeseries(time_axis="year-month")

# %% [markdown]
# # Process


# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("annual", scmdata.ScmRun(df_annual))
book.add_timeseries("monthly", scmdata.ScmRun(df_monthly))

# %%
book.metadata()

# %%
