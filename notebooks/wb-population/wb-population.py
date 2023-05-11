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
# # Worldbank Population Projections
#

# %%
import logging
import re
import tempfile
import zipfile

import pandas as pd
import scmdata

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

# %% [markdown]
# # Initialise

# %%
logging.basicConfig(level=logging.INFO)

# %%
metadata = load_nb_metadata("wb-population")
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

# Data has been cached by CR (hash came from original download)
data_fname = metadata.download_file()

# %%
zf = zipfile.ZipFile(data_fname)
zf.filelist

# %%
df = pd.read_csv(zf.open("Population-EstimatesData.csv"))

column_rename = {
    "Country Name": "name",
    "Country Code": "region",
    "Indicator Name": "variable",
    "Indicator Code": "variable_code",
}
df = df.rename(column_rename, axis=1)
df["scenario"] = "historical"
df["model"] = "World Bank"
df["source"] = f"wb-population @ {metadata.version}"
df["unit"] = ""
del df["Unnamed: 95"]

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


# This can take a minute or two
data = data.groupby("variable").map(get_units)

# %%
data.get_unique_meta("variable")


# %%
data.filter(variable="Population|*").meta[["variable", "unit"]].drop_duplicates()

pop = data.filter(variable="Population|*")
pop["unit"] = "thousands"
pop = pop / 1000

data = scmdata.run_append([pop, data.filter(variable="Population|*", keep=False)])
pop = data.filter(variable="Population|*").timeseries()

# %% [markdown]
# # Process

# %%
data.get_unique_meta("region")

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
# Entire dataset
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
