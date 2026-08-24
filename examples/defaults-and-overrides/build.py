# %% [markdown]
# # One build file, two books, one set of defaults
#
# Nothing in this file knows which values were inherited and which were overridden.
# The recipe resolves that before the build runs, and the manifest records the effective values.

# %%
import pandas as pd

import bookshelf

# %%
bs, book = bookshelf.setup()

# %%
raw = bs.use("raw")
emissions = pd.read_csv(raw.path)

# %%
book.write("emissions", emissions, type="timeseries", used=[raw])
book.publish()
