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
an updated version). A single dataset may produce multiple ``Books`` if different
representations are useful. These `Books`` can be deployed to a shared ``Bookshelf``so that they
are accessible by other users.

Users are able to use specific ``Books`` within other projects. The dataset and associated
metadata is fetched and cached locally. Specific versions of ``Books`` can also be pinned for
reproducibility purposes.

This repository contains the notebooks that are used to generate the ``Books``
as well as a CLI tool for managing these datasets.

This is a prototype and will likely change in future. Other potential ideas:
* [ ] Deployed data are made available via ``api.climateresource.com.au`` so that
they can be consumed queried smartly
* [ ] Simple web page to allow querying the data
* [ ] A standardised way of dealing with metadata (datapackage or the like?)

.. sec-end-index

License
-------

.. sec-begin-license

License to be determined.

.. sec-end-license
.. sec-end-long-description

.. sec-begin-installation

Installation
------------

``bookshelf`` isn't available via pypi, but can be installed via pip assuming
that you have access to the repository.

.. code:: bash

    pip install git+https://gitlab.com/climate-resource/bookshelf


.. sec-end-installation
