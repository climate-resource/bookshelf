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
import logging
import tempfile

import scmdata

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

# %%
logging.basicConfig(level=logging.INFO)

# %% tags=["parameters"]
local_bookshelf = tempfile.mkdtemp()
version = "2023-12-05-a"

# %%
metadata = load_nb_metadata("ndcs-cr", version=version)
metadata.dict()

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)


# %%
for idx, file in enumerate(metadata.dataset.files):
    file_data = scmdata.ScmRun(metadata.download_file(idx))
    scenario_name = file_data.get_unique_meta("scenario")
    variant = scenario_name[0].split("_")[-1]
    if variant in ["TP", "CR"]:
        variant_clean = "TP"
    elif variant in ["AVIVA", "CR-noOverrides"]:
        variant_clean = "CR-noOverrides"
    elif variant in ["UNFCCC"]:
        variant_clean = "UNFCCC"
    else:
        raise ValueError(f"Unknown variant: {variant}")
    file_data["variant"] = variant_clean
    book.add_timeseries(variant_clean, file_data)


# %%
book.metadata()
