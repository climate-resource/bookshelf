# %% [markdown]
# # The same version, rebuilt with different processing
#
# `chunk_size` changes how the totals are accumulated and nothing about the answer.
# Recording with `-p chunk_size=3` therefore moves the activity's `config_hash`
# while every output byte stays where it was.

# %%
import pandas as pd

import bookshelf

# %% [markdown]
# ## The build parameter
#
# It is a top-level assignment, because that is what `-p` replaces.
# A value nested inside a function or a dictionary would not be reachable from the command line.

# %%
chunk_size = 2

# %%
bs, book = bookshelf.setup()

# %%
raw = bs.use("raw")
emissions = pd.read_csv(raw.path)

# %% [markdown]
# ## Walking the input in chunks
#
# The chunking changes how the frame is walked, not how the numbers are added.
# The chunks are rejoined before the one groupby that computes the totals,
# so the arithmetic is identical for any chunk size rather than merely equal to rounding.

# %%
chunks = [emissions[start : start + chunk_size].dropna() for start in range(0, len(emissions), chunk_size)]

# %%
totals = (
    pd.concat(chunks)
    .groupby("region", as_index=False)["value"]
    .sum()
    .sort_values("region")
    .reset_index(drop=True)
)

# %%
book.write("totals", totals, used=[raw])
book.publish()
