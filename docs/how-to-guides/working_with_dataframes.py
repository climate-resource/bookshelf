# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Working with DataFrame Resources
#
# Books can contain two types of resources:
#
# - **Timeseries**: IAMC-formatted data returned as `scmdata.ScmRun` objects
# - **DataFrames**: Arbitrary tabular data returned as `pandas.DataFrame` objects
#
# This guide covers how to access DataFrame resources from a Book.

# %% [markdown]
# ## Loading a DataFrame
#
# Use the `dataframe()` method to retrieve a DataFrame resource by name:

# %%
from bookshelf import BookShelf

shelf = BookShelf()
book = shelf.load("wdi", version="v33")

# Get a DataFrame resource
country_metadata = book.dataframe("country_metadata")
country_metadata.head()

# %% [markdown]
# ## Supported Column Types
#
# DataFrame resources support the following column types:
#
# | Type | Description | Example |
# |------|-------------|---------|
# | `int` | Integer values | Population counts, IDs |
# | `float` | Floating point numbers | GDP per capita, percentages |
# | `str` | Text strings | Country names, codes |
# | `bool` | Boolean values | Flags, binary indicators |
# | `datetime` | Date and time values | Event timestamps |
# | `timedelta` | Time durations | Time intervals |

# %% [markdown]
# ## Error Handling
#
# If you request a DataFrame that doesn't exist, a `ValueError` is raised:

# %%
try:
    book.dataframe("nonexistent")
except ValueError as e:
    print(f"Error: {e}")

# %% [markdown]
# ## Combining with Timeseries Data
#
# DataFrame resources are useful for metadata tables that complement timeseries data.
# For example, a Book might contain emissions timeseries along with a country metadata
# DataFrame for lookups:

# %%
# Get timeseries data
# emissions = book.timeseries("core")

# Get metadata for joining/filtering
# countries = book.dataframe("country_metadata")

# Use pandas to join or filter as needed
# filtered = emissions.filter(region=countries[countries["income_group"] == "High"]["iso_code"].tolist())
