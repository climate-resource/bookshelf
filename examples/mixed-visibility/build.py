# %% [markdown]
# # A public book carrying one hidden resource
#
# The book is `public`, so every resource recorded after it is public unless it says otherwise.
# One registration says otherwise, and narrowing it changes that resource and nothing else.

# %%
import pandas as pd

import bookshelf

# %%
bs, book = bookshelf.setup()

# %%
raw = bs.use("raw")
emissions = pd.read_csv(raw.path)

# %% [markdown]
# ## The published outputs
#
# Neither names a tier, so both take the book's.

# %%
by_region = emissions.groupby("region", as_index=False)["value"].sum()
world = emissions[emissions["region"] == "World"].reset_index(drop=True)

# %%
book.write("by_region", by_region, used=[raw])
book.write("world", world, type="timeseries", used=[raw])

# %% [markdown]
# ## The embargoed output
#
# The intermediate working set is not fit to publish, so it is narrowed on its own registration.
# The book stays public. Narrowing one resource is a deliberate act about that resource.

# %%
working = emissions.assign(rank=emissions.groupby("year")["value"].rank(ascending=False))

# %%
book.write("working_set", working, used=[raw], visibility="hidden")
book.publish()
