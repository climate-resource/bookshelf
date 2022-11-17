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
book = LocalBook.create_from_metadata(
    metadata,
    local_bookshelf=local_bookshelf,
)

# %% [markdown]
# #  Fetch

# %%
rcmip_fname = metadata.download_file()
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
