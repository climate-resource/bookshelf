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
# Reading published data needs no credentials.
# Everything below runs unauthenticated.

# %% [markdown]
# ## Connecting
#
# `Bookshelf` is the synchronous facade.
# The deployment it talks to resolves from the `base_url` argument,
# then `$BOOKSHELF_URL`, then the production URL.
# These guides pin the staging deployment so they are reproducible.

# %%
import os

os.environ.setdefault("BOOKSHELF_URL", "https://bookshelf-staging.ovh.climateresource.com.au")

from bookshelf import Bookshelf

bs = Bookshelf()

# %% [markdown]
# The client is long lived by design.
# Token state lives in the credential provider and each surface pools connections,
# so build one client and keep it.
# A notebook can construct it plainly and never close it.
# A script or service should use it as a context manager,
# or call `bs.close()` at shutdown.

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
# A book holds one or more named entries.
# Index the book to get a `BookEntry`.

# %%
entry = book["magicc"]
entry

# %% [markdown]
# Asking for an entry that does not exist reports what is available,
# so a typo does not turn into a lookup through the API docs.

# %%
try:
    book["does-not-exist"]
except KeyError as exc:
    print(exc)

# %% [markdown]
# ## Exploring before pulling data
#
# `magicc` is a large entry.
# Explore its shape first rather than downloading it to find out.
#
# `facets()` returns each index column and its distinct values.
# `total_unique` is the count across the whole entry.

# %%
facets = entry.facets()
[(facet.column, facet.total_unique) for facet in facets.facets]

# %% [markdown]
# The values themselves are on each facet, each with the number of series carrying it.
# This is how to discover what is worth filtering on.

# %%
scenarios = next(facet for facet in facets.facets if facet.column == "scenario")
sorted((value.value, value.count) for value in scenarios.values)[:10]

# %% [markdown]
# `schema()` describes the timeseries structure without returning any values.
# `total_rows` is the number of series in the entry.

# %%
schema = entry.schema()
schema.columns, schema.total_rows

# %% [markdown]
# `preview()` returns a small tabular sample.

# %%
entry.preview(limit=5)

# %% [markdown]
# ## Pulling data
#
# `as_df()` returns pandas.
# For a timeseries entry it is wide indexed:
# the index carries the metadata dimensions and the columns are years.

# %%
frame = entry.as_df()
frame.shape

# %%
frame.index.names

# %% [markdown]
# ## Trimming on the server
#
# The full entry above is 1683 series across 751 years.
# Trim it in the request rather than after it arrives.
#
# `year_min` and `year_max` bound the year window.
# This is the safest control, because it touches the columns and leaves every index dimension intact.

# %%
window = entry.as_df(year_min=2020, year_max=2100)
window.shape

# %% [markdown]
# Filters select rows.
# On a book entry a filter is a plain `column=value` keyword.
# Multiple values for one column are OR'd.

# %%
world = entry.as_df(region="World", year_min=2020, year_max=2100)
world.shape

# %% [markdown]
# > **Warning: Filter syntax differs by path**
# >
# > A book entry accepts bare `column=value` filters only.
# > The richer `col.op` grammar (`region.in`, `variable.neq` and friends)
# > is **silently ignored** here rather than rejected,
# > so a mistyped filter returns the full unfiltered result.
# > Check the row count when a filter is meant to narrow something.

# %% [markdown]
# `top_n` keeps only the largest series,
# ranked by their latest non-null value over the whole filtered result.
# It is a presentation control, useful for a chart rather than an analysis.

# %%
top = entry.as_df(top_n=5, year_min=2020, year_max=2100)
top.shape

# %% [markdown]
# > **Warning: Trimming can drop index dimensions**
# >
# > When `top_n` or `limit` narrows the result to rows sharing a value,
# > the server drops that column from the index rather than repeating it.
# > The frame above has fewer index levels than the untrimmed one.
# > That is fine for a chart, and it breaks `as_scmrun()`,
# > which requires `region`, `unit`, `variable`, `model` and `scenario` to be present.
# > Use a year window and filters when the index has to stay whole.

# %%
top.index.names

# %% [markdown]
# `drop_constant=True` does the same thing deliberately,
# removing dimensions that carry a single value across the filtered data.

# %%
entry.as_df(region="World", year_min=2020, year_max=2100, drop_constant=True).index.names

# %% [markdown]
# ## Long format
#
# `as_long_df()` returns the tidy form,
# one row per series and year, with `year` and `value` columns.

# %%
entry.as_long_df(region="World", variable="Emissions|CO2", year_min=2020, year_max=2030).head()

# %% [markdown]
# ## Where to next
#
# - [Converting and plotting](convert_and_plot) covers the other converters,
#   the content cache, and hash verification.
# - [Reading asynchronously](read_asynchronously) covers the awaited surface.
