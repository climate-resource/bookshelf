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
# # Reading a published book
#
# This guide covers the consumer side of the SDK:
# addressing a book, choosing an edition, and pulling data out of it.
#
# Reading published data needs no credentials, so everything below runs unauthenticated.

# %% [markdown]
# ## Connecting
#
# `Bookshelf` provides a number of high-level functions on top of the bookshelf API.
# The deployment it talks to resolves from the `base_url` argument,
# then `$BOOKSHELF_URL`, then the production URL.

# %%
from bookshelf import Bookshelf, EntryNotFoundError

bs = Bookshelf()

# %% [markdown]
# The client is long lived by design.
# Token state lives in the credential provider and each surface pools connections,
# so build one client and keep it.
# A notebook can construct it plainly and never close it.
# A script or service should use it as a context manager, or call `bs.close()` at shutdown.

# %% [markdown]
# ## Addressing a book
#
# A book is addressed by volume and version.
# Omitting `edition=` resolves the latest published edition.

# %%
book = bs.book("rcmip-emissions", "v5.1.0")
book

# %% [markdown]
# The metadata carries the coordinates that were actually resolved.
# Record the edition whenever a result needs to be reproducible later,
# because the latest edition moves as data is reprocessed.

# %%
book.metadata.volume_name, book.metadata.version, book.metadata.edition

# %% [markdown]
# Pass `edition=` to pin one.
# This is the form to use in analysis that has to give the same answer next year.

# %%
pinned = bs.book("primap-hist", "v2.6", edition=5)
pinned.metadata.version, pinned.metadata.edition

# %% [markdown]
# ## Book entries
#
# A book holds one or more named entries, and indexing it returns a `BookEntry`.

# %%
entry = book["magicc"]
entry

# %% [markdown]
# Asking for an entry that does not exist reports what is available,
# so a typo does not turn into a lookup through the API docs.

# %%
try:
    book["does-not-exist"]
except EntryNotFoundError as exc:
    print(exc)

# %% [markdown]
# ## Exploring before pulling data
#
# `magicc` is a large entry, so explore its shape first rather than downloading it to find out.
# Three helpers describe an entry without pulling all of it:
# `facets()` returns each index column and its distinct values,
# `series_metadata()` lists the series one record at a time,
# and `preview()` returns a small sample.
#
# Start with `facets()`, where `total_unique` counts across the whole entry.

# %%
facets = entry.facets()
[(facet.column, facet.total_unique) for facet in facets.facets]

# %% [markdown]
# The values themselves hang off each facet, carrying the number of series that use them,
# which is how to work out what is worth filtering on.

# %%
scenarios = next(facet for facet in facets.facets if facet.column == "scenario")
sorted((value.value, value.count) for value in scenarios.values)[:10]

# %% [markdown]
# `series_metadata()` reports the same structure without any values at all,
# so `total_rows` is the number of series waiting behind it.

# %%
series = entry.series_metadata()
series.columns, series.total_rows

# %% [markdown]
# ## Previewing
#
# `preview()` has the platform pick a bounded sample.
# It returns a `DataPreview`, whose `data` is the frame
# and whose `completeness` says whether that frame holds every selected row.
# A wide timeseries row is one series, so `limit` counts series.

# %%
sample = entry.preview(limit=5)
sample.completeness, sample.data.shape

# %% [markdown]
# A preview takes the same selection as the converters below,
# plus `order`, `top_n` and `drop_constant`.
# `top_n` keeps the series with the largest latest value,
# and `drop_constant` drops the dimensions that hold one value across the returned series.
# These are presentation controls, useful for a chart rather than an analysis.
# A preview orders by dimension columns only, and `top_n` cannot take an order,
# because the platform would read the pair as the first series in that order.

# %%
top = entry.preview(filters={"region": "World"}, year_min=2020, year_max=2100, top_n=5, drop_constant=True)
top.data.index.names

# %% [markdown]
# ## Pulling data
#
# `as_df()` returns pandas.
# It always returns every selected row, so nothing is truncated.
# For a timeseries entry it is wide indexed:
# the index carries the metadata dimensions and the columns are years, labelled as strings.

# %%
frame = entry.as_df()
frame.shape

# %%
frame.index.names

# %% [markdown]
# ## Selecting
#
# `year_min` and `year_max` bound the inclusive year window.
# `filters` maps a column to a value, or to a list of values that are alternatives.
# Separate filters must all hold.
# A filter on a column the resource does not have raises `SelectionError`.

# %%
world = entry.as_df(filters={"region": ["World", "World|R5.2ASIA"]}, year_min=2020, year_max=2100)
world.shape

# %% [markdown]
# By default the selection applies to the verified cached file,
# so the first read downloads the whole entry and later reads cost nothing.
# `server_side=True` has the platform select instead, which transfers only the selected rows.
# The result is the same either way.

# %%
remote = entry.as_df(
    filters={"region": ["World", "World|R5.2ASIA"]},
    year_min=2020,
    year_max=2100,
    server_side=True,
)
remote.shape

# %% [markdown]
# ## Ordering
#
# `order` names the columns to sort by, each prefixed with `-` to sort descending.
# A year column works too, so this puts the largest 2100 values first.
# Missing values sort first either way, which is why these scenarios all run to 2100.
# Rows that tie keep no promised order.
# Without an `order` the row order is whatever the source holds,
# which can differ between the cached file and a server side read.

# %%
ranked = entry.as_df(
    filters={
        "region": "World",
        "variable": "Emissions|CO2",
        "scenario": ["ssp119", "ssp245", "ssp370", "ssp585"],
    },
    year_min=2020,
    year_max=2100,
    order="-2100",
)
ranked["2100"].droplevel(["activity_id", "mip_era", "region", "unit", "variable"])

# %% [markdown]
# ## Long format
#
# `as_long_df()` returns the tidy form,
# one row per series and year, with an integer `year` and a `value` column.

# %%
entry.as_long_df(
    filters={"region": "World", "variable": "Emissions|CO2"}, year_min=2020, year_max=2030
).head()

# %% [markdown]
# ## Where to next
#
# - [Converting and plotting](convert_and_plot) covers the other converters,
#   the content cache, and hash verification.
# - [Reading asynchronously](read_asynchronously) covers the awaited surface.
