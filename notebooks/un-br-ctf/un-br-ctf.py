# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -pycharm
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.15.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # UN-BR-CTF
#
# Here, we download the UNFCCC's Biennial Reports data from the Biennial Reports Data Interface (BR-DI).
# We only extract the GHG projections for now, but more can be added later if desired.

# %%
import logging
import tempfile
import zipfile

import numpy as np
import pandas as pd
import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %% [markdown]
# # Initialise

# %%
logging.basicConfig(level=logging.INFO)

# %%
metadata = load_nb_metadata("un-br-ctf")
metadata.dict()

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()

# %%
local_bookshelf

# %% [markdown]
# # Fetch

# %%
zip_fname = metadata.download_file()

# %%
zip = zipfile.ZipFile(zip_fname)
zip.namelist()

# %%
df = pd.read_excel(zip.open("GHGProjections.xlsx"))
df.head()

# %%
target_df = pd.read_excel(zip.open("Target.xlsx"))
target_df

# %% [markdown]
# # Process

# %% [markdown]
# Convert into useful metadata

# %%
df["Sector"].unique()

# %%
df["Gas"].unique()

# %%
# there is always either a Gas or a Sector specified. So we merge it, then translate
# this into category and variable information

df["GasSector"] = df["Gas"].fillna(df["Sector"])
df["GasSector"].unique()

# %%
# GasSector to variable, category
translation = {}
for sector in (
    "Energy",
    "Transport",
    "Industry/industrial processes",
    "Agriculture",
    "Forestry/LULUCF",
    "Waste management/waste",
    "Aviation",
    "Buildings",
    "Electricity",
    "Waste and Other",
    "Oil and Gas",
    "Business",
    "Residential",
    "Public",
    "Energy Supply",
    "Industrial Processes",
    "LULUCF",
    "Waste",
    "Navigation",
    "Product use and other",
    "Working machinery",
    "Solvents and Other Product Use",
):
    # sectors are total in their respective sector
    translation[sector] = ("Emissions|Total GHG", sector)
    translation[f"Other ({sector})"] = ("Emissions|Total GHG", sector)
translation["Total with LULUCF"] = ("Emissions|Total GHG", "National Total")
translation["Total without LULUCF"] = (
    "Emissions|Total GHG",
    "Total emissions excluding LULUCF",
)
for gas in ("CO2", "CH4", "N2O", "HFCs", "PFCs", "SF6", "NF3", "F-gases"):
    # gases are totals or w/o lulucf, as specified
    translation[gas] = (f"Emissions|{gas}", "National Total")
    translation[f"Other ({gas})"] = (f"Emissions|{gas}", "National Total")
    translation[f"{gas} emissions including net {gas} from LULUCF"] = (
        f"Emissions|{gas}",
        "National Total",
    )
    translation[f"{gas} emissions including {gas} from LULUCF"] = (
        f"Emissions|{gas}",
        "National Total",
    )
    translation[f"{gas} emissions excluding net {gas} from LULUCF"] = (
        f"Emissions|{gas}",
        "Total emissions excluding LULUCF",
    )
    translation[f"{gas} emissions excluding {gas} from LULUCF"] = (
        f"Emissions|{gas}",
        "Total emissions excluding LULUCF",
    )

for alias, orig in (
    ("Other (2.  IPPU)", "Industry/industrial processes"),
    ("Other (2 IPPU)", "Industry/industrial processes"),
    ("Other (3.  Agriculture)", "Agriculture"),
    ("Other (3 Agriculture)", "Agriculture"),
    ("Other (4.  LULUCF)", "LULUCF"),
    ("Other (4 LULUCF)", "LULUCF"),
    ("Other (LULUCF Contribution)", "LULUCF"),
    ("Other (5.  Waste)", "Waste"),
    ("Other (5 Waste)", "Waste"),
    ("Other (Total F-Gases (HFCs, PFCs & SF6))", "F-gases"),
    ("Other (Total F-gases (HFCs + PFCs + SF6))", "F-gases"),
    ("Other (Transport)", "Transport"),
    ("Other (Tansport)", "Transport"),
):
    translation[alias] = translation[orig]

var_map = {key: val[0] for key, val in translation.items()}
cat_map = {key: val[1] for key, val in translation.items()}

variable = df["GasSector"].map(var_map)
category = df["GasSector"].map(cat_map)

# we just handle the most important parts, top sectors and totals.
# some countries report a lot more detailed projections
unhandled = df["GasSector"][variable.isna()].unique()
unhandled

# %%
df_renamed = df.rename(
    columns={
        "PartyCode": "region",
        "DataSource": "source",
        "Unit": "unit",
        "Year1990": "1990",
    }
)
df_renamed["model"] = "BR-CTF"
df_renamed["category"] = category
df_renamed["variable"] = variable
dff = df_renamed[~df_renamed["category"].isna()]
dff = dff.drop(columns=["Sector", "Gas", "PartyName", "BaseYear", "YearBY", "GasSector"])
dff

# %%
df_wom = dff[
    [
        "region",
        "source",
        "model",
        "unit",
        "category",
        "variable",
        "1990",
        "WithoutMeasuresYear2020",
        "WithoutMeasuresYear2030",
    ]
]
df_wom = df_wom.rename(
    columns={
        "WithoutMeasuresYear2020": "2020raw",
        "WithoutMeasuresYear2030": "2030raw",
        "1990": "1990raw",
    }
)
df_wom["scenario"] = "without measures"
df_wom

# %%
df_wm = dff[
    [
        "region",
        "source",
        "model",
        "unit",
        "category",
        "variable",
        "1990",
        "WithMeasuresYear2020",
        "WithMeasuresYear2030",
    ]
]
df_wm = df_wm.rename(
    columns={
        "WithMeasuresYear2020": "2020raw",
        "WithMeasuresYear2030": "2030raw",
        "1990": "1990raw",
    }
)
df_wm["scenario"] = "with measures"
df_wm

# %%
df_wam = dff[
    [
        "region",
        "source",
        "model",
        "unit",
        "category",
        "variable",
        "1990",
        "WithAdditionalMeasuresYear2020",
        "WithAdditionalMeasuresYear2030",
    ]
]
df_wam = df_wam.rename(
    columns={
        "WithAdditionalMeasuresYear2020": "2020raw",
        "WithAdditionalMeasuresYear2030": "2030raw",
        "1990": "1990raw",
    }
)
df_wam["scenario"] = "with additional measures"
df_wam


# %%
def cleaner(str_val: str):
    if isinstance(str_val, float):
        return str_val
    if isinstance(str_val, int):
        return str_val
    str_val = str_val.replace("*", "")
    try:
        return float(str_val.replace(",", ""))
    except:
        parts = {x.strip() for x in str_val.split(",")}
        if "NE" in parts or parts == {"C"} or not parts or parts == {""}:
            return np.nan
        if parts.issubset({"IE", "NA", "NO"}):
            return 0
        print(parts)
        raise


def clean(df):
    ndf = df.copy()
    ndf["1990"] = df["1990raw"].map(cleaner)
    ndf["2020"] = df["2020raw"].map(cleaner)
    ndf["2030"] = df["2030raw"].map(cleaner)
    return ndf.drop(columns=["1990raw", "2020raw", "2030raw"])


cdf_wm = clean(df_wm)
cdf_wam = clean(df_wam)
cdf_wom = clean(df_wom)
cdf_wm["category"].unique()


# %%
def dedup(df: pd.DataFrame):
    return df.drop_duplicates(["category", "model", "region", "scenario", "source", "unit", "variable"])


# national total is duplicated in Sector and Gas, so needs to be deduplicated here.
ddf_wm = dedup(cdf_wm)
ddf_wam = dedup(cdf_wam)
ddf_wom = dedup(cdf_wom)
ddf_wm["category"].unique()

# %%
data_wom = scmdata.ScmRun(ddf_wom)
data_wm = scmdata.ScmRun(ddf_wm)
data_wam = scmdata.ScmRun(ddf_wam)
data = scmdata.run_append([data_wom, data_wm, data_wam])
data


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


udata = data.groupby("variable", "unit").map(convert_units)
udata.get_unique_meta("unit")

# %%
target_df["GwpUsed"].unique()


# %%
# need to read from the Target.xlsx table, assuming tables in one BUR are expressed
# in the same gwp_context as projections
def add_ghg_metric(run):
    region = run.get_unique_meta("region", True)
    source = run.get_unique_meta("source", True)

    gwp_used = target_df.query(f"PartyCode == {region!r} and DataSource == {source!r}")["GwpUsed"].iloc[0]

    if isinstance(gwp_used, float) and np.isnan(gwp_used):
        run["ghg_metric"] = np.nan
    elif gwp_used.startswith("4") or gwp_used.startswith("AR4"):
        run["ghg_metric"] = "AR4GWP100"
    elif gwp_used.startswith("2"):
        run["ghg_metric"] = "SARGWP100"
    else:
        raise ValueError(gwp_used)
    return run


gdata = udata.groupby(["region", "source"]).map(add_ghg_metric)

# %%
gdata.filter(source="BR_4").timeseries()

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("ghg_projections", gdata)

# %%
book.metadata()

# %% [markdown]
# This notebook is not responsible for uploading the book to the `BookShelf`.
# See docs for how to upload `Books` to the `BookShelf`

# %%
