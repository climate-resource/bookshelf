# %% [markdown]
# # A build whose outputs feed each other
#
# Each `book.write` hands back the resource it registered,
# so a later output cites the earlier one by passing that handle to `used=`.
# The lineage recorded is therefore the processing graph rather than a flat list of inputs.

# %%
import pandas as pd

import bookshelf

# %%
bs, book = bookshelf.setup()

# %% [markdown]
# ## The declared input

# %%
raw = bs.use("raw")
emissions = pd.read_csv(raw.path)

# %% [markdown]
# ## Step one: clean the input
#
# The only edge here is from the raw file, because nothing else exists yet.

# %%
cleaned = emissions.dropna().sort_values(["region", "year"]).reset_index(drop=True)

# %%
cleaned_resource = book.write("cleaned", cleaned, type="timeseries", used=[raw])

# %% [markdown]
# ## Step two: two summaries of the cleaned frame
#
# Both cite `cleaned` rather than `raw`, because that is what they were computed from.

# %%
by_region = cleaned.groupby("region", as_index=False)["value"].sum()
world = cleaned[cleaned["region"] == "World"].reset_index(drop=True)

# %%
by_region_resource = book.write("by_region", by_region, used=[cleaned_resource])
world_resource = book.write("world", world, type="timeseries", used=[cleaned_resource])

# %% [markdown]
# ## Step three: an output that joins two earlier ones
#
# `shares` is the regional total as a fraction of the world total,
# so it cites both of the outputs above and neither of the inputs.

# %%
world_total = float(world["value"].sum())
shares = by_region.assign(share=lambda frame: frame["value"] / world_total)

# %%
book.write("shares", shares, used=[by_region_resource, world_resource])
book.publish()
