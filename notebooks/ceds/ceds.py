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
# # CEDS
#
#
# We want to import by_region and by_region_sector

# %%
import fnmatch
import logging
import tempfile
import zipfile

import pandas as pd
import pooch
import pycountry
import scmdata

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

# %% [markdown]
# #  Initialise

# %%
logging.basicConfig(level="INFO")


# %% tags=["parameters"]
local_bookshelf = tempfile.mkdtemp()
version = "v2016_07_26"

# %%
metadata = load_nb_metadata("ceds", version=version)
metadata.dict()

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %% [markdown]
# #  Fetch data using pooch

# %%
ceds_fname = metadata.download_file()
ceds_data = zipfile.ZipFile(ceds_fname)
ceds_archive_fnames = [
    "./" + info.filename
    for info in ceds_data.filelist
    if "country_fuel" not in info.filename
]
ceds_archive_fnames

# %%
if version == "v2016_07_26":
    ceds_species = ["BC", "CH4", "CO2", "CO", "NH3", "NMVOC", "NOx", "OC", "SO2"]
else:
    ceds_species = ["BC", "CH4", "CO2", "CO", "N2O", "NH3", "NMVOC", "NOx", "OC", "SO2"]


# %% [markdown]
# # Process

# %%
def read_CEDS_format(fname: str) -> scmdata.ScmRun:
    fname_match = fnmatch.filter(ceds_archive_fnames, "*/" + fname)

    if len(fname_match) != 1:
        raise ValueError(f"Could not figure out match: {fname} -> {fname_match}")
    fname = fname_match[0].lstrip("./")

    df = pd.read_csv(ceds_data.open(fname)).rename(
        {"em": "variable", "country": "region", "units": "unit"}, axis=1
    )
    df["scenario"] = "Historical"
    df["model"] = f"CEDS ({metadata.version})"
    df["unit"] = df["unit"] + "/yr"
    df["unit"] = df["unit"].str.replace("kt", "kt ", regex=False)
    df["variable"] = "Emissions|" + df["variable"]
    df["region"] = df["region"].str.upper()

    columns = []
    for c in df.columns:
        if c.startswith("X"):
            columns.append(int(c[1:]))
        else:
            columns.append(c)
    df.columns = columns

    return scmdata.ScmRun(df)


# %%
res = []

for species in ceds_species:
    res.append(read_CEDS_format(f"{species}_CEDS_emissions_by_country_*.csv"))
res = scmdata.run_append(res)

# %%
res["variable"] = res["variable"].str.replace("SO2", "Sulfur")
res["variable"] = res["variable"].str.replace("NMVOC", "VOC")
res["unit"] = res["unit"].str.replace("NMVOC", "VOC")
res["unit"] = res["unit"].str.replace("NO2", "NOx")

# %%
oc_emms = res.filter(variable="Emissions|OC")
oc_emms["unit"] = "kt OC/yr"
bc_emms = res.filter(variable="Emissions|BC")
bc_emms["unit"] = "kt BC/yr"
remainder_emms = res.filter(variable=["Emissions|BC", "Emissions|OC"], keep=False)

res = scmdata.run_append([oc_emms, bc_emms, remainder_emms])

# %%
res.meta[["variable", "unit"]].drop_duplicates()

# %%
res.timeseries()

# %%
# Check country codes
for c in res.get_unique_meta("region"):
    if pycountry.countries.get(alpha_3=c) is None:
        print(c)

# %%
res["region"] = res["region"].str.replace("GLOBAL", "World")

# %%
res

# %%
book.add_timeseries("by_country", res)


# %% [markdown]
# # By country by sector

# %%
ceds_by_sector = []

for species in ceds_species:
    ceds_by_sector.append(
        read_CEDS_format(f"{species}_CEDS_emissions_by_sector_country_*.csv")
    )
ceds_by_sector = scmdata.run_append(ceds_by_sector)

# %%
ceds_by_sector.get_unique_meta("sector")

# %%
ceds_by_sector

# %% [markdown]
# # By grid sectors

# %%
ceds_mapping_fname = pooch.retrieve(
    "https://github.com/JGCRI/CEDS/raw/April-21-2021-release/input/gridding/gridding_mappings/CEDS_sector_to_gridding_sector_mapping.csv",
    known_hash="95f66a04095b3d9f6464d7a4713093ff2967c8a5f386d7b6addad30c40ff12d3",
)
ceds_sector_mapping = pd.read_csv(ceds_mapping_fname)
ceds_sector_mapping


# %%
def process_aggregate_sector(sector_column: str, sector: str):
    target_sector_info = ceds_sector_mapping[
        ceds_sector_mapping[sector_column] == sector
    ]
    ceds_sector_aggregate = ceds_by_sector.filter(
        sector=target_sector_info.CEDS_working_sector.to_list(), log_if_empty=False
    ).process_over(("sector"), "sum")
    ceds_sector_aggregate["sector"] = sector
    ceds_sector_aggregate["sector_short"] = target_sector_info[
        sector_column + "_short"
    ].unique()[0]
    return scmdata.ScmRun(ceds_sector_aggregate)


def extract_sectors(sector_column):
    target_sectors = ceds_sector_mapping[sector_column].unique()

    agg_sectors = []
    for sector in target_sectors:
        if isinstance(sector, str):
            agg_sectors.append(process_aggregate_sector(sector_column, sector))
    return scmdata.run_append(agg_sectors)


# %%
ceds_agg_sectors_intermediate = extract_sectors("CEDS_int_gridding_sector")
ceds_agg_sectors_intermediate.get_unique_meta("sector_short")

# %% [markdown]
# ### Final sectors
#
# aka CEDS9

# %%
ceds_agg_sectors_final = extract_sectors("CEDS_final_gridding_sector")
ceds_agg_sectors_final.get_unique_meta("sector_short")

# %%
ceds_agg_sectors_final

# %%
book.add_timeseries("by_sector_ipcc", ceds_by_sector)
book.add_timeseries("by_sector_intermediate", ceds_agg_sectors_intermediate)
book.add_timeseries("by_sector_final", ceds_agg_sectors_final)

# %% [markdown]
# # Checks

# %%
book.metadata()

# %%
