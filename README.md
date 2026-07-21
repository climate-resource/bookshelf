<!--- --8<-- [start:description] -->
# Bookshelf

`bookshelf` is one way [Climate Resource](https://climate-resource.com) reuses datasets across projects.

**Key info :**
[![Docs](https://img.shields.io/badge/docs-passing-blue)](https://climate-resource.github.io/bookshelf/)
[![Main branch: supported Python versions](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fclimate-resource%2Fbookshelf%2Fmain%2Fpyproject.toml)](https://github.com/climate-resource/bookshelf/blob/main/pyproject.toml)
[![Licence](https://img.shields.io/pypi/l/bookshelf?label=licence)](https://github.com/climate-resource/bookshelf/blob/main/LICENCE)

**PyPI :**
[![PyPI](https://img.shields.io/pypi/v/bookshelf.svg)](https://pypi.org/project/bookshelf/)
[![PyPI install](https://github.com/climate-resource/bookshelf/actions/workflows/install-pypi.yaml/badge.svg?branch=main)](https://github.com/climate-resource/bookshelf/actions/workflows/install-pypi.yaml)


**Tests :**
[![CI](https://github.com/climate-resource/bookshelf/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/climate-resource/bookshelf/actions/workflows/ci.yaml)
[![Coverage](https://codecov.io/gh/climate-resource/bookshelf/branch/main/graph/badge.svg)](https://codecov.io/gh/climate-resource/input4mips_validation)

**Other info :**
[![Last Commit](https://img.shields.io/github/last-commit/climate-resource/bookshelf.svg)](https://github.com/climate-resource/input4mips_validation/commits/main)
[![Contributors](https://img.shields.io/github/contributors/climate-resource/bookshelf.svg)](https://github.com/climate-resource/input4mips_validation/graphs/contributors)


The `bookshelf` represents a shared collection of curated datasets or `Books`.
Each `Book` is a preprocessed, versioned dataset including the notebooks used to produce it.
As the underlying datasets or processing are updated,
new `Books` can be created (with an updated version in the case of new data
or edition if the processing changed).
A single dataset may produce multiple `Resources` if different representations are useful.
These `Books` can be deployed to a shared `Bookshelf`so that they are accessible by other users.

Users are able to use specific `Books` within other projects.
The dataset and associated metadata is fetched and cached locally.
Specific versions of `Books` can also be pinned for reproducibility purposes.

This repository contains the notebooks that are used to generate the `Books`
as well as a CLI tool for managing these datasets.

This is a prototype and will likely change in future. Other potential ideas:

- Deployed data are made available via `api.climateresource.com.au` so that
  they can be consumed queried smartly
- Simple web page to allow querying the data

Each Book consists of a [datapackage](https://specs.frictionlessdata.io/data-package/)
description of the metadata.
This datapackage contains the associated `Resources` and their hashes.
Each `Resource` is fetched when it is first used and then cached for later use.


<!--- --8<-- [end:description] -->

Full documentation can be found at:
[https://climate-resource.github.io/bookshelf](https://climate-resource.github.io/bookshelf/).
We recommend reading the docs there because the internal documentation links
don't render correctly on GitHub's viewer.

## Getting Started

<!--- --8<-- [start:getting-started] -->

### For data consumers

`bookshelf` can be installed via pip:

```bash
pip install bookshelf
```

Fetching and using `Books` requires very little setup in order to start playing with
data.

```python
>> import bookshelf
>> shelf = bookshelf.BookShelf()
# Load the latest version of the MAGICC specific rcmip emissions
>> book = shelf.load("rcmip-emissions")
INFO:/home/user/.cache/bookshelf/v0.1.0/rcmip-emissions/volume.json downloaded from https://cr-prod-datasets-bookshelf.s3.us-west-2.amazonaws.com/v0.1.0/rcmip-emissions/volume.json
# On the first call this will fetch the data from the server and cache locally
>> book.timeseries("magicc")
INFO:/home/user/.cache/bookshelf/v0.1.0/rcmip-emissions/v0.0.2/magicc.csv downloaded from https://cr-prod-datasets-bookshelf.s3.us-west-2.amazonaws.com/v0.1.0/rcmip-emissions/v0.0.2/magicc.csv
<ScmRun (timeseries: 1683, timepoints: 751)>
Time:
        Start: 1750-01-01T00:00:00
        End: 2500-01-01T00:00:00
Meta:
                 activity_id mip_era        model region          scenario       unit                    variable
        0     not_applicable   CMIP5          AIM  World             rcp60   Mt BC/yr                Emissions|BC
        1     not_applicable   CMIP5          AIM  World             rcp60  Mt CH4/yr               Emissions|CH4
        2     not_applicable   CMIP5          AIM  World             rcp60   Mt CO/yr                Emissions|CO
        3     not_applicable   CMIP5          AIM  World             rcp60  Mt CO2/yr               Emissions|CO2
        4     not_applicable   CMIP5          AIM  World             rcp60  Mt CO2/yr  Emissions|CO2|MAGICC AFOLU
        ...              ...     ...          ...    ...               ...        ...                         ...
        1678  not_applicable   CMIP5  unspecified  World  historical-cmip5  Mt NH3/yr               Emissions|NH3
        1679  not_applicable   CMIP5  unspecified  World  historical-cmip5  Mt NOx/yr               Emissions|NOx
        1680  not_applicable   CMIP5  unspecified  World  historical-cmip5   Mt OC/yr                Emissions|OC
        1681  not_applicable   CMIP5  unspecified  World  historical-cmip5  Mt SO2/yr            Emissions|Sulfur
        1682  not_applicable   CMIP5  unspecified  World  historical-cmip5  Mt VOC/yr               Emissions|VOC

        [1683 rows x 7 columns]

# Subsequent calls use the result from the cache
>> book.timeseries("magicc")
```

### For data curators

If you wish to build/modify `Books` some additional dependencies are required. These can
be installed using:

```bash
pip install bookshelf-producer
```

Building and deploying datasets is managed via Jupyter notebooks and a small yaml file that
contains metadata about the dataset. These notebooks are stored as plain text Python files
using the [jupytext](https://jupytext.readthedocs.io/en/latest/) plugin for Jupyter.
See [notebooks/example.py](https://github.com/climate-resource/bookshelf/tree/main/notebooks/simple/simple.py)
for an example dataset.

Once the dataset has been developed, it can be deployed to the remote `BookShelf` so that
other users can consume it.

The dataset can deployed using the `publish` CLI as shown below:

```bash
bookshelf publish my-dataset
```

/// admonition | Note
Publishing to the remote bookshelf requires valid credentials.
Creating or obtaining these credentials is not covered in this documentation.
///

### For developers

<!--- --8<-- [start:getting-started-dev] -->

For development, we rely on [uv](https://docs.astral.sh/uv) for all our
dependency management. To get started, you will need to make sure that `uv`
is installed
([instructions here](https://docs.astral.sh/uv/getting-started/installation/)).

This project is a `uv` workspace,
which means that it contains more than one Python package.
`uv` commands will by default target the root `bookshelf` package,
but if you wish to target another package you can use the `--package` flag.

For all of work, we use our `Makefile`.
You can read the instructions out and run the commands by hand if you wish,
but we generally discourage this because it can be error prone.
In order to create your environment, run `make virtual-environment`.

If there are any issues, the messages from the `Makefile` should guide you
through. If not, please raise an issue in the [issue tracker][issue_tracker].

[issue_tracker]: https://github.com/climate-resource/bookshelf/issues?q=sort%3Aupdated-desc+is%3Aissue+is%3Aopen

<!--- --8<-- [end:getting-started-dev] -->
<!--- --8<-- [end:getting-started] -->
