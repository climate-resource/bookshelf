# %%
import logging
import re
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
    pattern = r"(\d{1,2}[A-Za-z]{3}\d{2,4}[a-z]_[\w-]+|\d{8}c_[\w-]+)(?=\.)"
    file_name = re.findall(pattern, file.url)[0]
    file_data = scmdata.ScmRun(metadata.download_file(idx))
    scenario_name = file_data.get_unique_meta("scenario")
    variant = scenario_name[0].split("_")[-1]
    if variant in ["TP", "CR"]:
        file_data["scenario"] = "TP"
    elif variant in ["AVIVA", "CR-noOverrides"]:
        file_data["scenario"] = "CR"
    else:
        raise ValueError(f"Unknown variant: {variant}")
    book.add_timeseries(file_name, file_data)


# %%
book.metadata()
