# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -pycharm
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.1
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
data_fname = metadata.download_file()

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
data_hist

# %%
# Merge the historical data with the projections to create a single timeseries
data = scmdata.run_append([data_hist.set_meta("scenario", "Medium variant"), data_proj])
data["historical_end_year"] = data_hist["year"].iloc[-1]
data.filter(year=range(2019, 2025)).timeseries()

# %%
available_types = data.get_unique_meta("type")
available_types

# %%
for t in available_types:
    data_subset = data.filter(type=t)

    # Use iso code as region identifer for compatibility with other data
    if t == "Country/Area":
        data_subset["country"] = data_subset["region"]
        data_subset["region"] = data_subset["ISO3 Alpha-code"]

    book.add_timeseries(
        f'by_{t.replace(" ", "_").replace("/", "_").lower()}',
        data_subset.drop_meta("ISO3 Alpha-code"),
    )

# %%
book.metadata()

# %% [markdown]
# That is all.
#
# This notebook is not responsible for uploading the book to the `BookShelf`. See docs for how to upload `Books` to the `BookShelf`

# %%
