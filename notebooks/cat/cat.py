# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -pycharm
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import glob
import os
import pathlib
import tempfile

import numpy as np
import pandas as pd
import pycountry
from scmdata import ScmRun

from bookshelf import LocalBook
from bookshelf.dataset_structure import print_dataset_structure
from bookshelf_producer.notebook import load_nb_metadata

# %% [markdown]
# ## How to download the data
# 1. Go to the Climate Action Tracker homepage
# 2. On the menu on the top, click the Countries drop-down list
# 3. Go to the each country's homepage, There is a button named "DATA DOWNLOAD" under the line chart.
# Click this button, the data can be downloaded

# %%
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()

# %%
metadata = load_nb_metadata("cat")
metadata.dict()

# %%
NOTEBOOK_DIR = pathlib.Path().resolve()
RAW_CAT_DATA_DIR = NOTEBOOK_DIR / metadata.version

csv_files = glob.glob(os.path.join(RAW_CAT_DATA_DIR, "*.xls*"))


# %%
def get_CAT_countries() -> dict[str, str]:
    """
    Retrieve country names and 3 letter code for countries in CAT

    Retrieve the country names and their corresponding ISO 3166-1 alpha-3 codes using the pycountry
    package. The function further supplements the country list with specific country names
    present in the CAT dataset that do not directly align with names in the pycountry package.

    Returns
    -------
    dict
        A dictionary mapping country names (keys) to their ISO 3166-1 alpha-3 codes (values).

    Notes
    -----
    The supplementary country names and their corresponding codes are manually defined
    within the function to ensure accuracy for specific cases not handled by pycountry.
    """
    countries = {}
    supplementary_countries = {
        "United States": "USA",
        "European Union": "EU27",
        "Vietnam": "VNM",
        "Russia": "RUS",
        "Iran": "IRN",
        "Korea": "KOR",
        "Türkiye": "TUR",
    }

    for country in pycountry.countries:
        countries[country.name] = country.alpha_3

    countries.update(supplementary_countries)

    return countries


# %%
CAT_df = []

for f in csv_files:
    # Skip initial 19 rows which contain dataset descriptions, same across files.
    CAT_data = pd.read_excel(open(f, "rb"), sheet_name="Assessment", skiprows=19)
    country_name = CAT_data.iloc[0, 3]
    date = CAT_data.iloc[1, 3]

    # Standardize country names to maintain consistency.
    if country_name == "USA":
        country_name = "United States"
    elif country_name == "EU ":
        country_name = "European Union"

    countries = get_CAT_countries()
    # Convert country names to 3-letter country codes (regions).
    if country_name in countries.keys():
        region_name = countries[country_name]

    year = str(date.year)
    month = f"{date.month:02}"
    day = f"{date.day:02}"

    model_version = "v" + year + month + day

    CAT_data = CAT_data.iloc[3:, 2:]
    CAT_data.columns = CAT_data.iloc[0]
    CAT_data = CAT_data[1:]

    # Insert meta data columns into dataframe.
    CAT_data.insert(2, "variable", "Emissions|Total GHG")
    CAT_data.insert(2, "unit", "MtCO2/yr")
    CAT_data.insert(0, "name", country_name)
    CAT_data.insert(0, "region", str(region_name))
    CAT_data.insert(0, "model_version", model_version)
    CAT_data.insert(0, "model", None)
    CAT_data.insert(0, "ghg_metric", "AR4GWP100")
    CAT_data.insert(0, "source_version", metadata.version)
    CAT_data.insert(0, "source", "CAT")

    # Consolidate current country's data with main dataframe.
    CAT_df.append(CAT_data)

CAT_df = pd.concat(CAT_df).rename(columns={"Graph label": "scenario"})

# Create a category column based on the information in the Sector/Type and scenario
CAT_df.loc[CAT_df["Sector/Type"].str.contains("Total, excl LULUCF", na=False), "category"] = "M.0.EL"
CAT_df.loc[CAT_df["Sector/Type"] == "LULUCF", "category"] = "M.LULUCF"

CAT_df.loc[CAT_df["scenario"].str.contains("Unconditional", na=False), "category"] = "M.0.EL"
CAT_df.loc[CAT_df["scenario"].str.contains("Conditional", na=False), "category"] = "M.0.EL"

# Identify nan values consistently
CAT_df = CAT_df.replace("-", np.nan)

CAT_df

# %%
CAT_df_ScmRun = ScmRun(CAT_df)

# %%
CAT_df_ScmRun.timeseries()


# %%
print_dataset_structure(CAT_df_ScmRun)

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("cat", CAT_df_ScmRun)

# %%
book.metadata()

# %%
