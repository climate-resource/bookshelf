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

# %% [markdown]
# # PRIMAP-SSP-downscaled
#
# Here, we download the SSP dataset from PRIMAP, which is downscaled to country level. We extract only the
# pathways produced the `PMSSPBIE` variant, which means
# * SSPs
# * with international bunkers removed before downscaling
# * Convergence downscaling with exponential convergence of emissions intensities and convergence before
# transitioning to negative emissions.
#
# We extract the SSP marker scenarios denoted by the scenario name `SSPX-Y.Z`. Additionally, we extract the
# SSP1, SSP2, SSP5 baseline scenarios for "REMIND-MAgPIE" denoted by `SSPX|Baseline`. In the case of
# `SSP5|Baseline` it is identical to the `SSP5-8.5` marker scenario, but duplicate timeseries with
# `scenario=SSP5|Baseline` have been included in the final dataset.
#
# Additional data from the whole dataset can be added as needed in future revisions.

# %%
import logging
import tempfile

import numpy as np
import pandas as pd
import pycountry
import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %% [markdown]
# # Initialise

# %%
logging.basicConfig(level=logging.INFO)

# %%
metadata = load_nb_metadata("primap-ssp-downscaled")
metadata.dict()

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()

# %%
local_bookshelf

# %% [markdown]
# # Fetch

# %%
data_fname = metadata.download_file()

# %%
df = pd.read_csv(data_fname)
df.head()

# %% [markdown]
# # Process

# %% [markdown]
# Filter the data we are interested in, set correct metadata, convert to scmdata

# %%
dff = df.query(
    "source == 'PMSSPBIE' and scenario in ("
    # Baseline
    "'SSP1BLREMMP', 'SSP2BLREMMP', "
    # Markers (SSP5-baseline has been duplicated)
    "'SSP119IMAGE', 'SSP126IMAGE', 'SSP245MESGB', 'SSP3BLAIMCGE', 'SSP434GCAM4',"
    " 'SSP460GCAM4', "
    "'SSP534REMMP', 'SSP5BLREMMP')"
)

# %%
dff["entity"].unique()

# %%
df_renamed = dff.rename(columns={"country": "region", "entity": "variable"})
df_renamed["variable"] = "Emissions|" + df_renamed["variable"]
df_renamed["category"] = df_renamed["category"].str.replace("IPCM0EL", "M.0.EL")

# %%
model_names = {
    ".*REMMP": "REMIND-MAgPIE",
    ".*IMAGE": "IMAGE",
    ".*MESGB": "MESSAGE-GLOBIOM",
    ".*AIMCGE": "AIM/CGE",
    ".*GCAM4": "GCAM4",
}

df_renamed["model"] = df_renamed["scenario"].replace(model_names, regex=True)
if set(df_renamed["model"].unique()) != set(model_names.values()):
    raise ValueError(f"Could not map all model names: {set(df_renamed['model'].unique())}")

# %%
scenario_map = {
    "SSP119IMAGE": "SSP1-1.9",
    "SSP126IMAGE": "SSP1-2.6",
    "SSP245MESGB": "SSP2-4.5",
    "SSP3BLAIMCGE": "SSP3-7.0",
    "SSP434GCAM4": "SSP4-3.4",
    "SSP460GCAM4": "SSP4-6.0",
    "SSP534REMMP": "SSP5-3.4",
    "SSP5BLREMMP": "SSP5-8.5",
}

df_renamed["scenario"] = df_renamed["scenario"].replace(scenario_map)
df_renamed["scenario"] = df_renamed["scenario"].replace(
    {k.replace(".*", ""): "" for k in model_names.keys()}, regex=True
)
# %%
data = scmdata.ScmRun(df_renamed)
data.head()


# %%
def rename_variable(v):
    return (
        v.replace("KYOTOGHG", "Kyoto GHG")
        .replace("HFCS", "HFCs")
        .replace("PFCS", "PFCs")
        .replace("FGASES", "F-Gases")
    )


data["variable"] = data["variable"].apply(rename_variable)


# %%
def convert_units(run):
    unit = run.get_unique_meta("unit", True)
    variable = run.get_unique_meta("variable", True)

    variable_dimension = variable.split("|")[1]

    if unit.endswith("CO2eq"):
        unit = f"{unit[:-5]} CO2 / yr"
        target_unit = "kt CO2 / yr"
    else:
        unit = f"{unit} {variable_dimension} / yr"
        target_unit = f"kt {variable_dimension} / yr"

    run["unit"] = unit

    return run.convert_unit(target_unit)


data = data.groupby("variable", "unit").map(convert_units)


# %%
def add_gwp_context(run):
    variable = run.get_unique_meta("variable", True)

    if variable.endswith("AR4"):
        variable = variable[:-3]
        gwp_context = "AR4GWP100"
    elif variable in ("Emissions|F-Gases", "Emissions|Kyoto GHG"):
        gwp_context = "SARGWP100"
    else:
        gwp_context = np.NaN

    run["variable"] = variable
    run["gwp_context"] = gwp_context
    return run


data = data.groupby("variable").map(add_gwp_context)

# %%
# Handle Baseline scenarios
data["scenario"] = data["scenario"].str.replace("BL", "|Baseline")

# Duplicate ssp585 which is also the REMIND baseline
remind_baseline = data.filter(model="REMIND-MAgPIE", scenario="SSP5-8.5").set_meta(
    "scenario", "SSP5|Baseline"
)
data = data.append(remind_baseline)

data.meta[["model", "scenario"]].drop_duplicates()
# %%
regions = {
    "ANNEXI",
    "AOSIS",
    "BASIC",
    "EARTH",
    "EU28",
    "LDC",
    "NONANNEXI",
    "UMBRELLA",
}


def rename_regions(d):
    region = d.get_unique_meta("region", True)

    country_data = pycountry.countries.get(alpha_3=region)
    if country_data is not None:
        d["country"] = country_data.name

    return d


data = data.groupby("region").map(rename_regions)

regions_used = []
for region in data.get_unique_meta("region"):
    country_data = pycountry.countries.get(alpha_3=region)
    if country_data is None:
        regions_used.append(region)

if set(regions_used) != regions:
    print(set(regions_used).symmetric_difference(regions))

# %%
data.get_unique_meta("region")

# %%
data.head()

# %%
data_countries = data.filter(region=regions, keep=False)
data_regions = data.filter(region=regions).drop_meta("country")
data_regions

# %%
data.get_unique_meta("scenario")

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("by_country", data_countries)
book.add_timeseries("by_region", data_regions)

# %%
book.metadata()

# %% [markdown]
# This notebook is not responsible for uploading the book to the `BookShelf`. See docs for how to upload
# `Books` to the `BookShelf`

# %%
