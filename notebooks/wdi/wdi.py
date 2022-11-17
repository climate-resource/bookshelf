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
metadata = load_nb_metadata("wdi")
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
df["source"] = f"WDI_{metadata.version}"
df["unit"] = ""
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


# This can take a minute or two
data = data.groupby("variable").map(get_units)

# %% [markdown]
# ## Emissions cleaning

# %%
data.filter(variable_code="EN.*").meta[["variable", "unit"]].drop_duplicates()

# %%
# Check units
data.meta[data.meta.unit.str.contains("kt")][["variable", "unit"]].drop_duplicates()

# %%
# Fix emissions units to be emissions/yr
data["unit"] = data["unit"].replace(
    "thousand metric tons of CO2 equivalent", "kt CO2-eq/yr"
)
data["unit"] = data["unit"].replace("kt of CO2 equivalent", "kt CO2-eq/yr")
data["unit"] = data["unit"].replace("Mt of CO2 equivalent", "Mt CO2-eq/yr")
# Check above shows that only emissions ts use "kt" as units
data["unit"] = data["unit"].replace("^kt$", "kt CO2/yr", regex=True)

# %%
# Rename variables
variable_map = {
    "Agricultural methane emissions": "Emissions|CH4|Agriculture",
    "Agricultural nitrous oxide emissions": "Emissions|N2O|Agriculture",
    "CO2 emissions": "Emissions|CO2",
    "CO2 emissions from electricity and heat production|Total": "Emissions|CO2",
    "CO2 emissions from gaseous fuel consumption": "Emissions|CO2|Gaseous Fuel Consumption",
    "CO2 emissions from liquid fuel consumption": "Emissions|CO2|Liquid Fuel Consumption",
    "CO2 emissions from manufacturing industries and construction": "Emissions|CO2|Manufacturing Industries and Construction",
    "CO2 emissions from other sectors|Excluding residential buildings and commercial and public services": "Emissions|CO2|Other Sectors",
    "CO2 emissions from residential buildings and commercial and public services": "Emissions|CO2|Residential Buildings and Commercial and Public Services",
    "CO2 emissions from solid fuel consumption": "Emissions|CO2|Solid Fuel Consumption",
    "CO2 emissions from transport": "Emissions|CO2|Transport",
    "Energy related methane emissions": "Emissions|CH4|Energy",
    "GHG net emissions/removals by LUCF": "Emissions|GHG|Net LUCF",
    "HFC gas emissions": "Emissions|HFCs",
    "Methane emissions": "Emissions|CH4",
    "Methane emissions in energy sector": "Emissions|CH4|Energy",
    "Nitrous oxide emissions": "Emissions|N2O",
    "Nitrous oxide emissions in energy sector": "Emissions|N2O|Energy",
    "Other greenhouse gas emissions": "Emissions|Other GHGs",
    "Other greenhouse gas emissions|HFC|PFC and SF6": "Emissions|HFCs|PFC and SF6",
    "PFC gas emissions": "Emissions|HFCs|PFC",
    "SF6 gas emissions": "Emissions|HFCs|SF6",
    "Total greenhouse gas emissions": "Emissions|GHG",
}

for old, new in variable_map.items():
    data["variable"] = data["variable"].replace(old, new)

# %%
data.filter(variable="Emissions*").meta[["variable", "unit"]].drop_duplicates()

# %% [markdown]
# ## Population

# %%
data.filter(variable="*Pop*").get_unique_meta("variable")

# %%
data.filter(variable="Population|*").meta[["variable", "unit"]].drop_duplicates()

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

# %%
# Entire dataset (~168 MB uncompressed)
book.add_timeseries("clean", data)

# %%
data.filter(variable="GDP").get_unique_meta("unit")

# %%
# Smaller subset of data that is typically used for analysis
subset = scmdata.run_append(
    [
        data.filter(variable="GDP|PPP", unit="constant 2017 international $"),
        data.filter(variable="GDP", unit="constant 2015 US$"),
        data.filter(variable="Emissions|*"),
        data.filter(variable="Population|Total"),
    ]
)
book.add_timeseries("core", subset)

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
