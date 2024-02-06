# %%
import logging
import pathlib
import re
import tempfile

import scmdata

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

# %%
logging.basicConfig(level=logging.INFO)

# %%
local_bookshelf = tempfile.mkdtemp()
version = "13Mar23a"

# %%
metadata = load_nb_metadata("ndcs-cr", version=version)
metadata.dict()

# %%
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %%
NOTEBOOK_DIR = pathlib.Path().resolve()
for file in metadata.dataset.files:
    pattern = r"(\d{1,2}[A-Za-z]{3}\d{2,4}[a-z]_[\w-]+|\d{8}c_[\w-]+)(?=\.)"
    file_name = re.findall(pattern, file.url)[0]
    RAW_DATA_PATH = NOTEBOOK_DIR / file.url
    file_data = scmdata.ScmRun(RAW_DATA_PATH)
    if file_name[-2:] == "TP":
        file_data["scenario"] = "TP"
    else:
        file_data["scenario"] = "CR"
    book.add_timeseries(file_name, file_data)

# %%
book.metadata()
