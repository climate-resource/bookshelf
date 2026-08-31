# %% [markdown]
# # A feedstock whose inputs and outputs are by different people
#
# The book credits the upstream team, because the data is theirs.
# Climate Resource assembled it and appears under `volume.maintainers`.
# Neither resource inherits the book's credit.
# `upstream` credits the team that published it, and `totals` credits whoever derived it,
# which here is us.

# %%
import pandas as pd

import bookshelf

# %%
bs, book = bookshelf.setup()

# %% [markdown]
# ## Reading the declared input
#
# The recipe states the authorship of `upstream`, so nothing about it is repeated here.

# %%
upstream = bs.use("upstream")
emissions = pd.read_csv(upstream.path)

# %% [markdown]
# ## Deriving one output
#
# `book.write` takes the same catalogue fields the recipe spells,
# so a derived output states its own authorship rather than the book's.

# %%
totals = emissions.groupby("region", as_index=False)["value"].sum()

# %%
book.write(
    "totals",
    totals,
    used=[upstream],
    description="Regional totals derived from the upstream workbook.",
    authors=[{"name": "Climate Resource", "email": "info@climate-resource.com"}],
    license="CC-BY-4.0",
    tags=["derived"],
)
book.publish()
