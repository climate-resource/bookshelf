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
# # Converting and plotting
#
# [Reading a published book](read_a_book) covered addressing a book and pulling pandas out of it.
# This guide covers the rest of the converter family,
# the local content cache,
# and getting a chart on screen.

# %%
import os

os.environ.setdefault("BOOKSHELF_URL", "https://bookshelf-staging.ovh.climateresource.com.au")

from bookshelf import Bookshelf

bs = Bookshelf()
entry = bs.book("rcmip-emissions", "v5.1.0")["magicc"]

# %% [markdown]
# ## The converter family
#
# Every converter takes the same trimming and filter arguments.
# They differ only in what they hand back.
#
# - `as_df()` returns wide indexed pandas.
# - `as_long_df()` returns tidy pandas.
# - `as_polars()` returns a Polars DataFrame.
# - `as_arrow()` returns a PyArrow Table.
# - `as_scmrun()` returns an `scmdata.ScmRun`.
#
# Polars and PyArrow need the `dataframes` extra.
# `as_scmrun()` needs the `scmrun` extra.
#
# ```bash
# uv add "bookshelf[dataframes,scmrun]"
# ```

# %%
selection = dict(region="World", variable="Emissions|CO2", year_min=2000, year_max=2100)

entry.as_polars(**selection).shape

# %%
entry.as_arrow(**selection).schema.names[:8]

# %% [markdown]
# The optional imports are resolved before any request is made,
# so a missing extra fails immediately rather than after downloading data.

# %% [markdown]
# ## Working in scmdata
#
# `as_scmrun()` is the route into the wider Climate Resource tooling.
# `ScmRun` requires `region`, `unit`, `variable`, `model` and `scenario` to be present,
# so the query has to leave those index dimensions intact.
#
# A year window and row filters are safe.
# `top_n` and `limit` are not,
# because the server drops index columns that carry a single value across the trimmed result.

# %%
run = entry.as_scmrun(year_min=1900, year_max=2100)
run

# %% [markdown]
# From here the usual `scmdata` vocabulary applies.

# %%
co2 = run.filter(variable="Emissions|CO2", region="World")
sorted(co2.get_unique_meta("scenario"))[:8]

# %% [markdown]
# ## Plotting
#
# `ScmRun` carries its own plotting helpers.

# %%
from matplotlib import pyplot as plt

fig, ax = plt.subplots(figsize=(10, 5), dpi=120)
co2.filter(scenario=["ssp119", "ssp245", "ssp585"], year=range(1990, 2101)).lineplot(hue="scenario", ax=ax)
ax.set_title("RCMIP CO2 emissions by scenario")
plt.tight_layout()

# %% [markdown]
# Pandas works just as well when `scmdata` is not wanted.

# %%
wide = entry.as_df(
    region="World",
    variable="Emissions|CO2",
    year_min=1990,
    year_max=2100,
    drop_constant=True,
)
fig, ax = plt.subplots(figsize=(10, 5), dpi=120)
wide.T.plot(ax=ax, legend=False)
ax.set_title("The same data straight from pandas")
plt.tight_layout()

# %% [markdown]
# ## Files and the content cache
#
# The converters go through the query API, which trims and filters on the server.
# To get the stored file itself, use `fetch()` for bytes or `as_path()` for a local path.
#
# Both verify the declared SHA256 before handing anything back.
# A mismatch raises `HashMismatchError` rather than returning suspect data.
# The verified bytes land in a local content cache,
# so a second call for the same resource does no network work.

# %%
path = entry.as_path()
path.stat().st_size

# %% [markdown]
# The cache is content addressed and shared across every book that points at the same bytes.
# Manage it from the command line.
#
# ```bash
# bookshelf cache path
# bookshelf cache clear
# ```

# %% [markdown]
# > **Warning: Prefer the book entry for timeseries**
# >
# > `entry.as_resource()` drops the book context and returns the lean resource handle.
# > That handle accepts the richer `col.op` filter grammar,
# > but `as_df()` on a lean **timeseries** resource does not currently
# > reassemble the year columns correctly.
# > Read timeseries through the book entry, as this guide does.
