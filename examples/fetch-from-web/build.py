# %% [markdown]
# # A feedstock whose input is fetched
#
# The build file reads the input exactly as a checked-in one is read.
# `bs.use` fetches the url, checks the bytes against the declared `sha256`,
# stores them in the content cache and catalogues a pointer to the upstream location.

# %%
import pandas as pd

import bookshelf

# %%
bs, book = bookshelf.setup()

# %%
raw = bs.use("raw")
co2 = pd.read_csv(raw.path)

# %% [markdown]
# ## Deriving one output
#
# The pointer records where the bytes came from, so `used=[raw]` cites upstream
# rather than a copy of it.

# %%
decadal = co2.assign(decade=co2["Year"] // 10 * 10).groupby("decade", as_index=False)["Mean"].mean().round(3)

# %%
book.write("annual_mean", co2, type="timeseries", used=[raw])
book.write("decadal_mean", decadal, used=[raw])
book.publish()
