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
# # Book data analysis example


# %% [markdown]
# ## Loading a dataset
#
# Begin by initializing a `BookShelf` object. Specify the desired volume and version to
# retrieve the corresponding book:

# %%
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
from matplotlib.pyplot import figure

from bookshelf import BookShelf

shelf = BookShelf()

volume = "rcmip-emissions"
version = "v5.1.0"
book = shelf.load(volume, version)

# %% [markdown]
# Once the book is loaded, access specific timeseries data in a wide format by using the
# `timeseries` function and specifying the book name. This data will be returned as an
# `scmdata.ScmRun` object. Alternatively, use the `get_long_format_data` function to obtain
# timeseries data in a long format, which returns a `pd.DataFrame` object:

# %%
data_wide = book.timeseries("complete")
# data_long = book.get_long_format_data("complete")

# %% [markdown]
# ## Filtering data

# For data in wide format, use the `filter` method from [ScmData](https://scmdata.readthedocs.io/en/latest/notebooks/scmrun.html#operations-with-scalars)
# to refine the dataset based on specific metadata criteria:

# %%
data_wide.filter(variable="Emissions|CO2|MAGICC AFOLU")

# %% [markdown]
# For long format data, employ `pandas` functionality to apply necessary filters.


# %% [markdown]
# ## Plotting
#
# For wide format data, visualize your data using built-in plotting functions from
# [ScmData](https://scmdata.readthedocs.io/en/latest/notebooks/plotting-with-seaborn.html).
# For instance, to generate a line plot based on filtered metadata:

# %%
figure(figsize=(10, 6), dpi=160)

data_wide.filter(variable="Emissions|CO2|MAGICC AFOLU").lineplot()

# %% [markdown]
# This approach allows you to efficiently load, filter, and visualize datasets from your bookshelf,
# facilitating in-depth analysis and insights.
