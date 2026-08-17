# %% [markdown]
# # The smallest legal feedstock
#
# One frame, built inline from literals.
# The recipe declares no resources, because this build reads nothing.

# %%
import pandas as pd

import bookshelf

# %%
bs, book = bookshelf.setup()

# %% [markdown]
# ## The data
#
# Every value is a literal, so the recorded bytes are the same on every machine.

# %%
emissions = pd.DataFrame(
    {
        "region": ["World", "World", "R5ASIA", "R5ASIA"],
        "variable": ["Emissions|CO2"] * 4,
        "unit": ["Mt CO2 / yr"] * 4,
        "year": [2020, 2050, 2020, 2050],
        "value": [36.7, 21.4, 17.2, 9.8],
    }
)

# %% [markdown]
# ## Writing it
#
# `book.write` registers the frame and attaches it under the same name in one call.

# %%
book.write("emissions", emissions, type="timeseries")
book.publish()
