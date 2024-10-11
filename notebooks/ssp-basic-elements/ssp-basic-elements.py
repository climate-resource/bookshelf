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
# # ssp-basic-elements
# The basic elements from the SSP database. This includes country-level projections of population and GDP


# %%
import logging
import tempfile

import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %% [markdown]
# #  Initialise

# %%
logging.basicConfig(level="INFO")

# %%
metadata = load_nb_metadata("ssp-basic-elements")
metadata.dict()

# %% tags=["parameters"]
local_bookshelf = tempfile.mkdtemp()

# %%
local_bookshelf

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %% [markdown]
# #  Fetch

# %%
metadata.download_file()
ssp_country_fname = metadata.download_file(0)
ssp_regions_fname = metadata.download_file(1)

# %%
basic_elements_country = scmdata.ScmRun(ssp_country_fname, lowercase_cols=True)
basic_elements_country

# %%
basic_elements_regions = scmdata.ScmRun(ssp_regions_fname, lowercase_cols=True)
basic_elements_regions

# %%
basic_elements_regions.get_unique_meta("variable")

# %% [markdown]
# # Process
#
# We don't need the population breakdowns so we filter them away

# %%
basic_elements_country = basic_elements_country.filter(
    variable=["Population", "Population|Urban|Share", "GDP|PPP"]
)
basic_elements_regions = basic_elements_regions.filter(
    variable=["Population", "Population|Urban|Share", "GDP|PPP"]
)

# %%
len(basic_elements_country.get_unique_meta("region"))


# %%
def clean_scenario(s):
    return s[:4]


basic_elements_country["scenario"] = basic_elements_country["scenario"].apply(clean_scenario)
basic_elements_regions["scenario"] = basic_elements_regions["scenario"].apply(clean_scenario)

# %%
basic_elements_regions.meta[["scenario", "model"]].drop_duplicates()

# %%
book.add_timeseries("by_country", basic_elements_country)
book.add_timeseries("by_region", basic_elements_regions)

# %%
book.metadata()

# %%
