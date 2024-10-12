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
# # PRIMAP-hist
#
# The PRIMAP-hist dataset of historical GHG emissions.

# %%
# Need to think about how to handle notebook dependencies
# !pip install pycountry

# %%
import logging
import re
import tempfile

import pandas as pd
import pycountry
import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %% [markdown]
# # Initialise

# %%
logging.basicConfig(level=logging.INFO)

# %% tags=["parameters"]
# This cell contains additional parameters that are controlled using papermill
local_bookshelf = tempfile.mkdtemp()
version = "v2.4.2"

# %%
metadata = load_nb_metadata("primap-hist", version=version)
metadata.dict()


# %% [markdown]
# # Fetch

# %% [markdown]
# We recommend using `pooch` to download input data. `Pooch` will verify that the
# downloaded file matches the expected hash as a check that the download was performed
# successfully.

# %%
data_df = pd.read_csv(metadata.download_file())
data_df

# %%
col_renames = {
    "scenario (PRIMAP-hist)": "scenario",
    "entity": "variable",
    "area (ISO3)": "region",
    "country": "region",  # v2.2
    "category (IPCC2006_PRIMAP)": "category",
}
data_df_renamed = data_df.rename(col_renames, axis=1)
data_df_renamed["model"] = "PRIMAP-hist"
data_df_renamed["variable"] = "Emissions|" + data_df_renamed["variable"]

# %%
data = scmdata.ScmRun(data_df_renamed, lowercase_cols=True)
data.head()


# %% [markdown]
# # Process
#
# Minor renames and enrichment


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
data["scenario"] = data["scenario"].str.replace("HISTCR", "Historical|Country Reported")
data["scenario"] = data["scenario"].str.replace("HISTTP", "Historical|Third Party")

# %%
# Extract the GWP context from brackets
pattern = re.compile(r".*\((.*)\)")
pattern_all_but = re.compile(r"(.*) \(.*")

m = re.match(pattern_all_but, "Emissions|Kyoto GHG (AR4GWP100)")


def add_gwp_context(v):
    m = re.match(pattern, v)
    if m:
        return m.group(1)
    return None


def remove_gwp_from_variable(v):
    m = re.match(pattern_all_but, v)
    if m:
        return m.group(1)
    return v


# %%
data["gwp_context"] = data["variable"].apply(add_gwp_context)
data["variable"] = data["variable"].apply(remove_gwp_from_variable)

# %%
data.get_unique_meta("gwp_context")

# %%
data.get_unique_meta("variable")

# %%
data.timeseries()

# %%
regions = {
    "ANNEXI",
    "ANT",
    "AOSIS",
    "BASIC",
    "EARTH",
    "EU27BX",
    "LDC",
    "NONANNEXI",
    "UMBRELLA",
}


# %%
def rename_regions(d):
    region = d.get_unique_meta("region", True)

    country_data = pycountry.countries.get(alpha_3=region)
    if country_data is not None:
        d["country"] = country_data.name

    return d


# Rename regions
data = data.groupby("region").map(rename_regions)


regions_used = []
for region in data.get_unique_meta("region"):
    country_data = pycountry.countries.get(alpha_3=region)
    if country_data is None:
        regions_used.append(region)

if set(regions_used) != regions:
    print(set(regions_used).symmetric_difference(regions))

# %%
data.get_unique_meta("unit")


# %%
def convert_units(run):
    unit = run.get_unique_meta("unit", True)

    # This assumes that the form of 'X * gigagram / a'
    # The unit conversion should fail if this assumption proves wrong
    variable_dimension = unit.split()[0]

    # Pint changed the unit ordering in v2.4
    if variable_dimension == "Gg":
        variable_dimension = unit.split()[1]

    target_unit = f"kt {variable_dimension} / yr"
    return run.convert_unit(target_unit)


data = data.groupby("unit").map(convert_units)

# %%
data.get_unique_meta("unit")

# %%
data.get_unique_meta("category")

# %%
data.timeseries()

# %%
data_countries = data.filter(region=regions, keep=False)
data_regions = data.filter(region=regions).drop_meta("country")
data_regions

# %%
data_countries.get_unique_meta("region")

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
book.add_timeseries("by_country", data_countries, write_long=False)
book.add_timeseries("by_region", data_regions, write_long=False)

# %%
book.metadata()

# %% [markdown]
# This notebook is not responsible for uploading the book to the `BookShelf`. See docs for how to upload
# `Books` to the `BookShelf`

# %%
