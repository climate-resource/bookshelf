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

# %%
import logging
import tempfile

import pooch
import scmdata

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

# %% [markdown]
# #  Initialise

# %%
logging.basicConfig(level="INFO")

# %%
metadata = load_nb_metadata("rcmip-emissions")
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
rcmip_fname = pooch.retrieve(
    "https://rcmip-protocols-au.s3-ap-southeast-2.amazonaws.com/v5.1.0/rcmip-emissions-annual-means-v5-1-0.csv",
    known_hash="2af9f90c42f9baa813199a902cdd83513fff157a0f96e1d1e6c48b58ffb8b0c1",
)

# %%
rcmip_emissions = scmdata.ScmRun(rcmip_fname, lowercase_cols=True)
rcmip_emissions

# %% [markdown]
# # Process

# %%
rcmip_emissions.get_unique_meta("variable")

# %%
book.add_timeseries("complete", rcmip_emissions)


# %%
magicc_emissions = rcmip_emissions.filter(
    variable=[
        "Emissions|BC",
        "Emissions|CH4",
        "Emissions|CO",
        "Emissions|CO2",
        "Emissions|CO2|MAGICC AFOLU",
        "Emissions|CO2|MAGICC Fossil and Industrial",
        "Emissions|F-Gases|*",
        "Emissions|Montreal Gases|*",
        "Emissions|N2O",
        "Emissions|NH3",
        "Emissions|NOx",
        "Emissions|OC",
        "Emissions|Sulfur",
        "Emissions|VOC",
    ]
)

# %%
magicc_emissions.meta[["variable", "unit"]].drop_duplicates()

# %%
# for v in magicc_emissions.get_unique_meta("variable"):
#     plt.figure()
#     magicc_emissions.filter(variable=v, region="World").lineplot()

# %%
book.add_timeseries("magicc", magicc_emissions)

# %%
book.metadata()
