# %% [markdown]
# # One build file, several upstream versions
#
# `bookshelf record --version` selects the book to build.
# The build file names no version, so the recorder and the build can never disagree.

# %%
import pandas as pd

import bookshelf

# %%
bs, book = bookshelf.setup()

# %%
raw = bs.use("raw")
emissions = pd.read_csv(raw.path)

# %%
totals = emissions.groupby("region", as_index=False)["value"].sum()

# %%
book.write("emissions", emissions, type="timeseries", used=[raw])
book.write("totals", totals, used=[raw])
book.publish()
