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
    file_data["variant"] = variant
    book.add_timeseries(variant, file_data)


# %%
book.metadata()
