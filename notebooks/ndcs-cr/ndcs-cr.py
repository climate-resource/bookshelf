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
    file_data = scmdata.ScmRun(metadata.download_file(idx))
    pattern = r"(\d{1,2}[A-Za-z]{3}\d{2,4}[a-z]_[\w-]+|\d{8}c_[\w-]+)(?=\.)"
    file_name = re.findall(pattern, file.url)[0]
    if file.url[-2:] == "TP":
        file_data["scenario"] = "TP"
    else:
        file_data["scenario"] = "CR"
    book.add_timeseries(file.url, file_data)


# %%
book.metadata()
