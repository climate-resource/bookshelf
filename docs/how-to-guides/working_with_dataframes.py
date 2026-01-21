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
# This guide covers how to work with DataFrame resources.

# %% [markdown]
# ## Setup
#
# First, let's create a sample Book with a DataFrame resource to demonstrate the functionality.

# %%
import tempfile

import pandas as pd

from bookshelf import LocalBook

# Create a temporary directory for our example book
local_bookshelf = tempfile.mkdtemp()

# Create a new book
book = LocalBook.create_new("example_book", "v1.0.0", local_bookshelf=local_bookshelf)

# %% [markdown]
# ## Adding a DataFrame Resource
#
# Use the `add_dataframe()` method to add a DataFrame resource to a Book:

# %%
# Create sample country metadata
country_metadata = pd.DataFrame(
    {
        "iso_code": ["USA", "CHN", "IND", "DEU", "BRA"],
        "name": ["United States", "China", "India", "Germany", "Brazil"],
        "region": ["North America", "Asia", "Asia", "Europe", "South America"],
        "population": [331_000_000, 1_412_000_000, 1_380_000_000, 83_000_000, 214_000_000],
        "gdp_per_capita": [65_280.0, 10_500.0, 1_900.0, 46_200.0, 7_500.0],
    }
)

# Add the DataFrame to the book
book.add_dataframe("country_metadata", country_metadata)

# %% [markdown]
# ## Retrieving a DataFrame
#
# Use the `dataframe()` method to retrieve a DataFrame resource by name:

# %%
# Retrieve the DataFrame
retrieved_df = book.dataframe("country_metadata")
retrieved_df

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
# Here's an example with datetime columns:

# %%
events_df = pd.DataFrame(
    {
        "event": ["COP26", "COP27", "COP28"],
        "date": pd.to_datetime(["2021-11-01", "2022-11-06", "2023-11-30"]),
        "duration_days": pd.to_timedelta(["14 days", "14 days", "13 days"]),
    }
)

book.add_dataframe("climate_events", events_df)
book.dataframe("climate_events")

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
# ## Compression Options
#
# DataFrame resources support different compression algorithms:
#
# - `"zstd"` (default): Zstandard compression - faster and smaller files
# - `"gzip"`: Gzip compression - wider compatibility
# - `None`: No compression

# %%
# Add with gzip compression
book.add_dataframe("country_metadata_gzip", country_metadata, compression="gzip")

# Add without compression
book.add_dataframe("country_metadata_raw", country_metadata, compression=None)

# %% [markdown]
# ## Combining with Timeseries Data
#
# DataFrame resources are useful for metadata tables that complement timeseries data.
# For example, a Book might contain emissions timeseries along with a country metadata
# DataFrame for lookups:
#
# ```python
# # Get timeseries data
# emissions = book.timeseries("emissions")
#
# # Get metadata for joining/filtering
# countries = book.dataframe("country_metadata")
#
# # Filter to high-income countries
# high_gdp_countries = countries[countries["gdp_per_capita"] > 20000]["iso_code"].tolist()
# filtered = emissions.filter(region=high_gdp_countries)
# ```
