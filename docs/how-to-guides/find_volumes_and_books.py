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
# # Finding volumes and books
#
# [Reading a published book](read_a_book) assumed you already knew the coordinates.
# This guide covers the step before that: working out what is on the shelf at all.
#
# Discovery needs no credentials, though an authenticated caller sees more,
# because private volumes belonging to your organisation join the results.

# %%
import os

os.environ.setdefault("BOOKSHELF_URL", "https://bookshelf-staging.ovh.climateresource.com.au")

from bookshelf import Bookshelf

bs = Bookshelf()

# %% [markdown]
# ## Listing the catalogue
#
# `search_volumes()` with no arguments returns everything you can see.

# %%
catalogue = bs.search_volumes()
len(catalogue.items), catalogue.has_more

# %% [markdown]
# Each result carries enough to decide whether it is worth opening,
# including the latest version and edition, so a summary needs no further requests.

# %%
for volume in sorted(catalogue.items, key=lambda item: item.name)[:8]:
    print(f"{volume.name:32} {volume.latest_version or '-':16} {volume.license}")

# %% [markdown]
# ## Searching
#
# The first argument is free text over the name, title and summary.

# %%
found = bs.search_volumes("emissions")
[volume.name for volume in found.items]

# %% [markdown]
# Filters narrow it further, and they combine with AND rather than OR.
# The vocabulary matches the discovery profile a volume is published with:
# `topic`, `keyword`, `region`, `publisher`, `license`, `coverage_year`,
# `resource_type` and `deprecated`.

# %%
[volume.name for volume in bs.search_volumes(license="CC-BY-4.0").items]

# %% [markdown]
# `deprecated=False` is worth knowing about.
# A superseded volume stays readable so old analyses keep working,
# so excluding it is how you avoid building something new on a dataset that has moved on.

# %%
active = bs.search_volumes("emissions", deprecated=False)
[volume.name for volume in active.items]

# %% [markdown]
# ## Paging
#
# The response carries `total`, `limit`, `offset` and `has_more`.
# Read `has_more` rather than comparing counts, and page with `offset`.

# %%
page = bs.search_volumes(limit=5)
print(f"showing {len(page.items)} of {page.total}, more to come: {page.has_more}")

if page.has_more:
    following = bs.search_volumes(limit=5, offset=5)
    print(f"next page starts at {following.items[0].name}")

# %% [markdown]
# ## Every book in a volume
#
# A volume holds many books, one per version and edition.
# `list_books()` returns all of them, oldest first,
# walking the pages itself so you do not have to.

# %%
books = bs.list_books("primap-hist")
[f"{book.version}_e{book.edition:03}" for book in books]

# %% [markdown]
# Versions sort component by component, comparing numeric runs as numbers,
# so `v2.10` lands after `v2.9` instead of before it.
# The last entry is therefore the newest book, which is what
# `bs.book(volume, version)` resolves when you leave `edition=` off.

# %%
newest = books[-1]
newest.version, newest.edition, newest.status

# %% [markdown]
# Pass `status=` to look at something other than published books.
# Drafts are only visible to the organisation that owns them.

# %% [markdown]
# ## From discovery to data
#
# Discovery hands back coordinates, and [reading a book](read_a_book) takes it from there.

# %%
entry = bs.book("primap-hist", newest.version)["by_region"]
entry.as_df(year_min=2018, year_max=2020, top_n=5).iloc[:5, :3]

# %% [markdown]
# ## From the command line
#
# The same catalogue is searchable without writing any Python,
# which is often faster when you are just orienting yourself.
#
# ```bash
# bookshelf search emissions
# bookshelf search --licence CC-BY-4.0 --no-deprecated
# bookshelf search --facets            # the valid values for each filter
# bookshelf show primap-hist           # one volume, its versions and editions
# bookshelf show primap-hist@v2.6/by_region
# ```
#
# Every command takes `--json` for a machine readable form.
