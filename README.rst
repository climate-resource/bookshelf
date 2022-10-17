Bookshelf
=========

Brief summary
+++++++++++++

.. sec-begin-long-description
.. sec-begin-index

``bookshelf`` is how Climate Resource reuses datasets across projects


The ``bookshelf`` represents a shared collection of curated datasets or ``Books``. Each
``Book`` is a preprocessed, versioned dataset including the notebooks used to produce it.
As the underlying datasets or processing are updated, new ``Books`` can be created (with
an updated version). A single dataset may produce multiple ``Resources`` if different
representations are useful. These ``Books`` can be deployed to a shared ``Bookshelf``
so that they are accessible by other users.

Users are able to use specific ``Books`` within other projects. The dataset and associated
metadata is fetched and cached locally. Specific versions of ``Books`` can also be pinned for
reproducibility purposes.

This repository contains the notebooks that are used to generate the ``Books``
as well as a CLI tool for managing these datasets.

This is a prototype and will likely change in future. Other potential ideas:

* Deployed data are made available via ``api.climateresource.com.au`` so that
  they can be consumed queried smartly
* Simple web page to allow querying the data

Each Book consists of a `datapackage <https://specs.frictionlessdata.io/data-package/>`_
description of the metadata. This datapackage contains the associated ``Resources`` and
their hashes. Each ``Resource`` is fetched when it is first used and then cached for later use

.. sec-end-index

License
-------

.. sec-begin-license

Licensed under MIT. See the LICENSE file for more information

.. sec-end-license
.. sec-end-long-description

.. sec-begin-installation

Installation
------------

``bookshelf`` isn't available via pypi, but can be installed via pip assuming
that you have access to the repository.

.. code:: bash

    pip install git+https://gitlab.com/climate-resource/bookshelf


Usage
-----

Data Consumer
=============

Fetching and using ``Books`` requires very little setup in order to start playing with
data.

.. code:: python

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

Data Curator
============

If you wish to build/modify ``Books`` some additional dependencies are required. These can
be installed using:

.. code:: bash

  pip install "bookshelf[notebooks]"

Building and deploying datasets is managed via Jupyter notebooks and a small yaml file that
contains metadata about the dataset. These notebooks are stored as plain text Python files
using the `jupytext <https://jupytext.readthedocs.io/en/latest/>`_ plugin for Jupyter.
See `notebooks/example.py <https://gitlab.com/climate-resource/bookshelf/-/blob/master/notebooks/example.py>`_
for an example dataset. As part of the CI, these notebooks are run on each commit to ensure
that the ``Books`` remain reproducible.

Once the dataset has been developed, it can be deployed to the remote ``BookShelf`` so that
other users can consume it. The dataset can deployed using the ``save`` CLI as shown below:

.. code:: bash

  bookshelf save my-dataset

This command first builds the ``Book`` in an isolated environment to ensure a reproducible
build. Once the build is successful, the resulting ``Book``, including ``Resources`` is
uploaded to an AWS S3 bucket. Deploying datasets requires valid AWS credentials, as well as ``BOOKSHELF_BUCKET`` and
``BOOKSHELF_BUCKET_PREFIX`` environment variables. These can be managed using a local
``.env`` file.

.. sec-end-installation
