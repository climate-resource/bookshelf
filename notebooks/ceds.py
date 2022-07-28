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

# %%
metadata = load_nb_metadata("ceds")
metadata.dict()

# %% tags=["parameters"]
local_bookshelf = tempfile.mkdtemp()

# %%
local_bookshelf

# %%
book = LocalBook.create_new(
    metadata.name, version=metadata.version, local_bookshelf=local_bookshelf
)

# %% [markdown]
# #  Fetch

# %%
file_to_fetch = f"doi:{metadata.dataset['doi']}/{metadata.dataset['files'][0]}"
file_to_fetch

# %%
ceds_fname = pooch.retrieve(
    file_to_fetch,
    known_hash="95c236e7a8f7b3728453fdae8dc0e84ea8a0ec4a485dd0e96d6eff8fb40759a0",
)
ceds_fname

# %%
ceds_data = zipfile.ZipFile(ceds_fname)
[info.filename for info in ceds_data.filelist]

# %%
ceds_species = ["BC", "CH4", "CO2", "CO", "N2O", "NH3", "NMVOC", "NOx", "OC", "SO2"]
date_code = "2021_04_21"


# %% [markdown]
# # Process

# %%
def read_CEDS_format(fname: str) -> scmdata.ScmRun:
    df = pd.read_csv(ceds_data.open(fname)).rename(
        {"em": "variable", "country": "region", "units": "unit"}, axis=1
    )
    df["scenario"] = "Historical"
    df["model"] = f"CEDS ({metadata.dataset['version']})"
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
    res.append(read_CEDS_format(f"{species}_CEDS_emissions_by_country_{date_code}.csv"))
res = scmdata.run_append(res)

# %%
res["variable"] = res["variable"].str.replace("SO2", "Sulfur")
res["variable"] = res["variable"].str.replace("NMVOC", "VOC")
res["unit"] = res["unit"].str.replace("NMVOC", "VOC")

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
book.add_timeseries("by_country", res)


# %%
book.metadata()

# %%
