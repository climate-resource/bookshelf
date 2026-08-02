# Notebooks

This directory contains notebooks that produce `Book`s.
Each notebook corresponds with a single `Volume`,
which is the collection of `Book`s sharing a `name`.

Each notebook has a matching `.yaml` file holding the metadata for the `Book`.
See `example_volume/example_volume.yaml` for the expected format.

New datasets should not be added here.
Start a feedstock repository from the
[copier template](https://github.com/climate-resource/copier-bookshelf-dataset) instead.
The notebooks kept here are examples and test fixtures,
and are being migrated out.

`example_volume` is the minimal pair to copy when you want something to read.

For more detail, see the
[development docs](https://climate-resource.github.io/bookshelf/latest/development/).
