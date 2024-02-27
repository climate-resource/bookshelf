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

"""
Outlines the process for creating a new volume within the bookshelf system.

Includes steps for initial setup, metadata storage, logging configuration, data loading,
transformation, and finally, local book creation and resource addition.
"""

# %% [markdown]
# # Creating a new volume

# %% [markdown]
# ## Initial setup
#
# Begin by creating a new folder within the `notebooks` directory. Name this
# folder after the volume you wish to create. Copy `simple.py` and `simple.yaml`
# from the `examples/simple` directory into your new folder, renaming them to
# `{volume}.py` and `{volume}.yaml`, respectively. These files will serve
# as templates to kickstart your volume creation process.

# %% [markdown]
# ## Metadata storage
#
# Updating the `{volume}.yaml` with the volume's metadata, this may include:
#
# - name of the volume
# - edition
# - license
# - metadata about author and author_email
# - data dictionary
# - detailed version information
# - etc.

# %% [markdown]
# ## Logging configuration
#
# Set up the basic configuration for logging:

# %%
import logging
import tempfile

from scmdata import testing

from bookshelf import LocalBook
from bookshelf.notebook import load_nb_metadata

logging.basicConfig(level=logging.INFO)

# %% [markdown]
# ## Metadata loading
#
# Load and verify the volume's metadata

# %%
metadata = load_nb_metadata("example_volume/example_volume")
metadata.dict()

# %% [markdown]
# ## Data loading and transformation
#
# Load the data intended for storage in the volume. This data may be sourced
# locally, scraped from the web, or downloaded from a server. For data downloads,
# we recommend using `pooch` to ensure integrity through hash verification.
#
# Once the data is loaded, perform any necessary manipulations to prepare it for storage.
# Convert the data to an `scmdata.ScmRun` object if it isn't already in this format.

# %%
data = testing.get_single_ts()
data.timeseries()

# %% [markdown]
# ## Local book creation
#
# Initialize a local book instance using the prepared metadata:

# %%
# create and return a unique temporary directory
local_bookshelf = tempfile.mkdtemp()
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %% [markdown]
# ## Resource creation
#
# Add a new `Resource` to the Book utilizing the `scmdata.ScmRun` object. This process
# involves copying the timeseries data into a local file, then calculating the hash of the
# file's contents to ensure data integrity. Additionally, the timeseries data is transformed
# into a long format, followed by a hash calculation of this transformed data. Utilizing
# these hashes allows for a straightforward verification process to determine if the files
# have undergone any modifications.

# %%
book.add_timeseries("example_resource_name", data)

# %% [markdown]
# Display the `Book`'s metadata, which encompasses all metadata about the Book and
# its associated
# `Resources`:

# %%
book.metadata()

# %% [markdown]
# The metadata outlined above is available for clients to download and use for fetching
# the `Book`'s`Resources`. Upon deployment, the Book becomes immutable, meaning any
# modifications to its metadata or data necessitate the release of a new Book version.
