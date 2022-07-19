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
import re
import tempfile
import zipfile

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
metadata = load_nb_metadata("example")
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
    url="http://databank.worldbank.org/data/download/WDI_csv.zip",
    known_hash="af42db151faf58d3398136b05f8c171db40be921567f536f069f8d1732a3039e",
)
data_fname

# %%
zf = zipfile.ZipFile(data_fname)
zf.filelist

# %%
df = pd.read_csv(zf.open("WDIData.csv"))

column_rename = {
    "Country Name": "name",
    "Country Code": "region",
    "Indicator Name": "variable",
    "Indicator Code": "variable_code",
}
df = df.rename(column_rename, axis=1)
df["scenario"] = "historical"
df["model"] = "World Bank"
df["source"] = "WDI_v13"
df[
    "unit"
] = ""  # Units are hard to get. They aren't in the WDISeries.csv column that they should be
del df["Unnamed: 66"]

# %%
data = scmdata.ScmRun(df)
data.head()

# %%
unit_regex = re.compile(r"\s\((.*)\)")


def get_units(run):
    variable = run.get_unique_meta("variable", True)

    unit_match = re.search(unit_regex, variable)
    if unit_match:
        unit = unit_match.group(1)
        run["unit"] = unit
        variable = re.sub(unit_regex, "", variable)
    toks = variable.split(", ")
    variable = "|".join(
        [t.capitalize() if not t[0].isupper() else t for t in toks]
    ).rstrip("|")
    run["variable"] = variable

    return run


data = data.groupby("variable").map(get_units)

# %%
data.get_unique_meta("variable")

# %%
data.filter(variable="GDP|PPP")

# %%
data.filter(variable="GDP|PPP", unit="constant 2017 international $").lineplot(
    units="region", estimator=None
)

# %% [markdown]
# # Process

# %%
data.get_unique_meta("region")

# %%
book = LocalBook.create_new(
    name=metadata.name, version=metadata.version, local_bookshelf=local_bookshelf
)

# %% [markdown]
# Create a new `Resource` in the `Book` using the RF `scmdata.ScmRun` object. This function copies the timeseries to a local file and calculate the hash of this file. This hash can be used to check if the files have been modified.

# %%
book.add_timeseries("clean", data)

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
