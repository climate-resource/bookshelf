# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # The golden fixture build
#
# A build that records one pointer and two derived frames, with no network access.
# It is the input to the bundle golden regression test,
# so every value that would otherwise vary by machine or by run is pinned here.

# %%
from uuid import UUID

import pandas as pd

import bookshelf

# %% [markdown]
# ## Pinned identity
#
# `code_ref` is normally derived from git and `runner` from the hostname,
# so both are passed explicitly to keep the recorded manifest identical everywhere.
# The UUIDs are pinned for the same reason.

# %%
CODE_REF = "https://example.invalid/golden@0000000000000000000000000000000000000000"
RUNNER = "golden"
ACTIVITY_ID = UUID("0197a000-0000-7000-8000-00000000a001")
UPSTREAM_ID = UUID("0197a000-0000-7000-8000-00000000b001")
EMISSIONS_ID = UUID("0197a000-0000-7000-8000-00000000b002")
SUMMARY_ID = UUID("0197a000-0000-7000-8000-00000000b003")

# %%
bs, book = bookshelf.setup(version="v1.0.0")

# %% [markdown]
# ## The derived frames
#
# The frames are built inline from literals, so the recorded bytes depend on nothing outside this file.

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
summary = emissions.groupby("region", as_index=False)["value"].sum()

# %%
with bs.activity(
    activity_id=ACTIVITY_ID,
    code_ref=CODE_REF,
    config={"source": "golden/upstream", "statistic": "regional-sum"},
    runner=RUNNER,
) as activity:
    # A pointer names bytes that stay where they are,
    # so the derived frames have real lineage without the build reaching the network.
    upstream = activity.register_external(
        type="tabular",
        uri="https://example.invalid/golden/upstream-v1.0.0.csv",
        logical_key="golden/upstream",
        tracking_id=UPSTREAM_ID,
    )
    emissions_resource = activity.register(
        emissions,
        type="timeseries",
        logical_key="golden/emissions",
        tracking_id=EMISSIONS_ID,
        used=[upstream],
    )
    # Inputs accumulate within a run,
    # so the recorded summary cites the upstream pointer as well as the frame passed here.
    summary_resource = activity.register(
        summary,
        type="tabular",
        logical_key="golden/summary",
        tracking_id=SUMMARY_ID,
        used=[emissions_resource],
    )

# %% [markdown]
# ## Framing the book

# %%
book.attach(emissions_resource, name_in_book="emissions")
book.attach(summary_resource, name_in_book="summary")
book.publish()
