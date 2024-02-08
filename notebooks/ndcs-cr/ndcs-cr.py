# %%
import logging
import tempfile

import scmdata

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

# %%
logging.basicConfig(level=logging.INFO)

# %% tags=["parameters"]
local_bookshelf = tempfile.mkdtemp()
version = "13Mar23a"

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
    else:
        raise ValueError(f"Unknown variant: {variant}")
    file_data["variant"] = variant_clean
    book.add_timeseries(variant_clean, file_data)


# %%
book.metadata()
