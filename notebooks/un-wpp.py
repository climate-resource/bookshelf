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

import numpy as np
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
metadata = load_nb_metadata("un-wpp")
metadata.dict()

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()
local_bookshelf

# %%
book = LocalBook.create_new(
    metadata.name, version=metadata.version, local_bookshelf=local_bookshelf
)

# %% [markdown]
# # Fetch

# %% [markdown]
# We recommend using `pooch` to download input data. `Pooch` will verify that the
# downloaded file matches the expected hash as a check that the download was performed
# successfully.

# %%
expected_hash = "e8cef388f9f4d16acb5c82bb007d25b2280cc6c78214faa7c8c6962d6d54d43d"

data_fname = pooch.retrieve(
    url="https://population.un.org/wpp/Download/Files/1_Indicators%20(Standard)/EXCEL_FILES/1_General/WPP2022_GEN_F01_DEMOGRAPHIC_INDICATORS_COMPACT_REV1.xlsx",
    known_hash=expected_hash,
)

# %%
df_hist = pd.read_excel(data_fname, sheet_name="Estimates", skiprows=16)
df_proj = pd.read_excel(data_fname, sheet_name="Medium variant", skiprows=16)

# %%
value_cols = [
    "Total Population, as of 1 January (thousands)",
    "Total Population, as of 1 July (thousands)",
    "Male Population, as of 1 July (thousands)",
    "Female Population, as of 1 July (thousands)",
    "Population Density, as of 1 July (persons per square km)",
    "Population Sex Ratio, as of 1 July (males per 100 females)",
    "Median Age, as of 1 July (years)",
    "Natural Change, Births minus Deaths (thousands)",
    "Rate of Natural Change (per 1,000 population)",
    "Population Change (thousands)",
    "Population Growth Rate (percentage)",
    "Population Annual Doubling Time (years)",
    "Births (thousands)",
    "Births by women aged 15 to 19 (thousands)",
    "Crude Birth Rate (births per 1,000 population)",
    "Total Fertility Rate (live births per woman)",
    "Net Reproduction Rate (surviving daughters per woman)",
    "Mean Age Childbearing (years)",
    "Sex Ratio at Birth (males per 100 female births)",
    "Total Deaths (thousands)",
    "Male Deaths (thousands)",
    "Female Deaths (thousands)",
    "Crude Death Rate (deaths per 1,000 population)",
    "Life Expectancy at Birth, both sexes (years)",
    "Male Life Expectancy at Birth (years)",
    "Female Life Expectancy at Birth (years)",
    "Life Expectancy at Age 15, both sexes (years)",
    "Male Life Expectancy at Age 15 (years)",
    "Female Life Expectancy at Age 15 (years)",
    "Life Expectancy at Age 65, both sexes (years)",
    "Male Life Expectancy at Age 65 (years)",
    "Female Life Expectancy at Age 65 (years)",
    "Life Expectancy at Age 80, both sexes (years)",
    "Male Life Expectancy at Age 80 (years)",
    "Female Life Expectancy at Age 80 (years)",
    "Infant Deaths, under age 1 (thousands)",
    "Infant Mortality Rate (infant deaths per 1,000 live births)",
    "Live Births Surviving to Age 1 (thousands)",
    "Under-Five Deaths, under age 5 (thousands)",
    "Under-Five Mortality (deaths under age 5 per 1,000 live births)",
    "Mortality before Age 40, both sexes (deaths under age 40 per 1,000 live births)",
    "Male Mortality before Age 40 (deaths under age 40 per 1,000 male live births)",
    "Female Mortality before Age 40 (deaths under age 40 per 1,000 female live births)",
    "Mortality before Age 60, both sexes (deaths under age 60 per 1,000 live births)",
    "Male Mortality before Age 60 (deaths under age 60 per 1,000 male live births)",
    "Female Mortality before Age 60 (deaths under age 60 per 1,000 female live births)",
    "Mortality between Age 15 and 50, both sexes (deaths under age 50 per 1,000 alive at age 15)",
    "Male Mortality between Age 15 and 50 (deaths under age 50 per 1,000 males alive at age 15)",
    "Female Mortality between Age 15 and 50 (deaths under age 50 per 1,000 females alive at age 15)",
    "Mortality between Age 15 and 60, both sexes (deaths under age 60 per 1,000 alive at age 15)",
    "Male Mortality between Age 15 and 60 (deaths under age 60 per 1,000 males alive at age 15)",
    "Female Mortality between Age 15 and 60 (deaths under age 60 per 1,000 females alive at age 15)",
    "Net Number of Migrants (thousands)",
    "Net Migration Rate (per 1,000 population)",
]


# %%
def prep_df(df, **kwargs):
    df = df[~df["Year"].isna()]

    df_wide = (
        df.melt(
            id_vars=[
                "Region, subregion, country or area *",
                "ISO3 Alpha-code",
                "Type",
                "Year",
            ],
            value_vars=value_cols,
        )
        .set_index(
            [
                "Region, subregion, country or area *",
                "ISO3 Alpha-code",
                "Type",
                "Year",
                "variable",
            ]
        )
        .unstack("Year")
    )
    na_values = "..."
    df_wide[df_wide == na_values] = np.nan

    df_wide.columns = df_wide.columns.get_level_values("Year").astype(int)
    df_wide = df_wide.reset_index().rename(
        {"Region, subregion, country or area *": "region", "Type": "type"}, axis=1
    )

    # Strip units from between brackets
    df_wide["unit"] = df_wide["variable"].str.extract(r"\((.*)\)")
    df_wide["variable"] = df_wide["variable"].str.extract(r"(.*) \(.*")

    df_wide["region"] = df_wide["region"].str.replace("WORLD", "World")

    for k in kwargs:
        df_wide[k] = kwargs[k]

    return df_wide.reset_index(drop=True)


prepped = prep_df(
    df_hist, model="World Population Prospects 2022", scenario="Historical"
)

prepped

# %%
data_hist = scmdata.ScmRun(
    prep_df(df_hist, model="World Population Prospects 2022", scenario="Historical")
)
data_proj = scmdata.ScmRun(
    prep_df(df_proj, model="World Population Prospects 2022", scenario="Medium variant")
)


# %% [markdown]
# ## Population
#
# Now we can slice the data set up into different views


# %%
data = scmdata.run_append([data_hist, data_proj])
data

# %%
available_types = data.get_unique_meta("type")
available_types

# %%
for t in available_types:
    book.add_timeseries(
        f'by_{t.replace(" ", "_").replace("/", "_").lower()}', data.filter(type=t)
    )

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
