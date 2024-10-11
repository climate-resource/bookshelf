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
from bookshelf_producer.notebook import load_nb_metadata

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
    "./" + info.filename for info in ceds_data.filelist if "country_fuel" not in info.filename
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


def _fix_units(data: scmdata.ScmRun) -> scmdata.ScmRun:
    data["variable"] = data["variable"].str.replace("SO2", "Sulfur")
    data["variable"] = data["variable"].str.replace("NMVOC", "VOC")
    data["unit"] = data["unit"].str.replace("NMVOC", "VOC")

    return (
        data.set_meta("unit", "kt NOx/yr", variable="Emissions|NOx", log_if_empty=False)
        .set_meta("unit", "kt OC/yr", variable="Emissions|OC", log_if_empty=False)
        .set_meta("unit", "kt BC/yr", variable="Emissions|BC", log_if_empty=False)
    )


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

    data = scmdata.ScmRun(df)
    data["region"] = data["region"].str.replace("GLOBAL", "World")
    return _fix_units(data)


# %%
ceds_by_country = []

for species in ceds_species:
    ceds_by_country.append(read_CEDS_format(f"{species}_CEDS_emissions_by_country_*.csv"))
ceds_by_country = scmdata.run_append(ceds_by_country)

# %%
# Check units
ceds_by_country.meta[["variable", "unit"]].drop_duplicates()

# %%
# Check country codes
for c in ceds_by_country.get_unique_meta("region"):
    if pycountry.countries.get(alpha_3=c) is None:
        print(c)

# %%
ceds_by_country

# %%
book.add_timeseries("by_country", ceds_by_country)


# %% [markdown]
# # By country by sector

# %%
ceds_by_sector = []

for species in ceds_species:
    ceds_by_sector.append(read_CEDS_format(f"{species}_CEDS_emissions_by_sector_country_*.csv"))
ceds_by_sector = scmdata.run_append(ceds_by_sector)
ceds_by_sector.get_unique_meta("region")

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
    target_sector_info = ceds_sector_mapping[ceds_sector_mapping[sector_column] == sector]
    ceds_sector_aggregate = ceds_by_sector.filter(
        sector=target_sector_info.CEDS_working_sector.to_list(), log_if_empty=False
    ).process_over("sector", "sum")
    ceds_sector_aggregate["sector"] = sector
    ceds_sector_aggregate["sector_short"] = target_sector_info[sector_column + "_short"].unique()[0]
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
# CEDS has *very* precise numbers. This can cause rounding errors if we don't preround these values
# This rounding does not necessarily loose any information.
book.add_timeseries("by_sector_ipcc", ceds_by_sector.round(8))
book.add_timeseries("by_sector_intermediate", ceds_agg_sectors_intermediate.round(8))
book.add_timeseries("by_sector_final", ceds_agg_sectors_final.round(8))

# %% [markdown]
# # Checks

# %%
book.metadata()

# %%
