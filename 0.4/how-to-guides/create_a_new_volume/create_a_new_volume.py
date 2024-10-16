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
# # Creating a new volume

# %% [markdown]
# ## Initial setup
#
# The first step for creating a new dataset is to create a new repository.
# By splitting datasets out into different repositories,
# we can ensure that the data release/management processes are much simpler.
# To make this step easier,
# we have created a [copier](https://copier.readthedocs.io/en/latest/) repository
# that can be used to easily initialise a new repository using the following.
#
# ```
# uvx copier copy gh:climate-resource/copier-bookshelf-dataset directory/to/new/repo
# cd directory/to/new/repo
# git add .
# git commit -m "Initial commit"
# ```
#
# Copier will then ask you a few questions to set up the new repository.
# After the new repository is generated,
# a few more administration steps are required to get fully set up.
# * A new repository should be created on GitHub
# * The git remote `origin` should be updated to point to the new repository
#   (`git remote add origin <new-repo-ssh-url>`)
# * A `PERSONAL_ACCESS_TOKEN` secret is required to be added to the repository
#   ([instructions](https://github.com/climate-resource/copier-bookshelf-dataset#required-secrets))
#
# After this, you can start creating your new dataset.

# %% [markdown]

# ## Repository structure
# The repository structure is as follows:
#
# * pyproject.toml: A description of the repository and its dependencies
# * src/{dataset_name}.py: The main script that generates the dataset
#   (this file includes a [jupytext](https://jupytext.readthedocs.io/en/latest/) header)
# * src/{dataset_name}.yaml: The metadata that describes the dataset and the versions that are to be
#   processed.
#
# Some examples for source files for datasets can be found in the `notebooks` directory
# in this repository.

# %% [markdown]
# ## Metadata storage
#
# Updating the `{example_volume}.yaml` with the volume's metadata, this may include:
#
# - name of the volume
# - edition
# - license
# - metadata about author and author_email
# - data dictionary
# - detailed version information
# - etc.

# %% [markdown]
# ## Steps in processing a dataset
# Below the steps to process a dataset are described in more detail.
# These steps are included in the `src/{dataset_name}.py` file as a starting point,
# but can be modified as needed.

# %% [markdown]
# ### Logging configuration
#
# Load the packages and set up the basic configuration for logging:

# %%
import logging
import tempfile

from scmdata import testing

from bookshelf import LocalBook
from bookshelf_producer.notebook import load_nb_metadata

logging.basicConfig(level=logging.INFO)

# %% [markdown]
# ### Metadata loading
# If multiple versions are to be processed,
# the version can be passed as an argument to the script using a paper parameter section.
# Papermill will inject a new set of parameters into the notebook when it is run.
#
# ```
### %% tags=["parameters"]
## This cell contains additional parameters that are controlled using papermill
# local_bookshelf = tempfile.mkdtemp()
# version = "v3.4"
# ```
# %% [markdown]
# ## Metadata loading
#
# Load and verify the volume's metadata

# %%
metadata = load_nb_metadata("example_volume/example_volume")
metadata.dict()

# %% [markdown]
# ### Data loading and transformation
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
# ### Local book creation
#
# Initialize a local book instance using the prepared metadata:

# %%
# create and return a unique temporary directory
local_bookshelf = tempfile.mkdtemp()
book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)

# %% [markdown]
# ### Resource creation
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
# It is important to note that the steps provided herein pertain to the process of
# constructing a volume locally. This process does not cover the publication of the volume.

# %% [markdown]

# ## Generation
# The volumes for a book can be generated using:
#
# ```
# make run
# ```
#
# This will run the `src/{volume_name}.py` script for each version in the configuration file
# and output data to the `dist/` directory.
# The output folder contains the generated data, metadata, and the processed notebooks.
#
# The CI will automatically run this command during a Merge Request
# to verify that that processing scripts are valid.
