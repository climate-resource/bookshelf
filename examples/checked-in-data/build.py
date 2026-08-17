# %% [markdown]
# # A feedstock whose input is checked in
#
# The recipe addresses `raw` by `path:` rather than by `uri:`,
# so the recorder computes the digest from the file rather than verifying a declared one.

# %%
import pandas as pd

import bookshelf

# %%
bs, book = bookshelf.setup()

# %% [markdown]
# ## Reading the declared input
#
# `bs.use` resolves the name the recipe declares, and registers it as an input of this build.

# %%
raw = bs.use("raw")
emissions = pd.read_csv(raw.path)

# %% [markdown]
# ## Deriving one output
#
# `used=[raw]` is what records the lineage edge from the input to this output.

# %%
totals = emissions.groupby("region", as_index=False)["value"].sum()

# %%
book.write("totals", totals, used=[raw])
book.publish()
