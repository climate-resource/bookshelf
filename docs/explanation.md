# Explanation

This page covers the background of the project
and the reasoning behind how it is put together.

## The problem

Climate Resource works on many projects that draw on the same public datasets.
Those datasets are rarely usable as published.
They arrive as spreadsheets, as zip files behind a login,
or as CSVs whose column names change between releases.
Every project that needs one ends up writing its own cleaning code.

That has three costs.
The same work is repeated.
Two projects can silently disagree about what the same dataset says.
Reproducing a result from a year ago means reconstructing whatever the cleaning code did at the time.

`bookshelf` helps us deplicate that effort.

## The shape of the solution

The processing for a dataset lives in a notebook, in version control.
Running that notebook produces a `Book`, which is the processed dataset plus its metadata.
`Book`s are uploaded to a remote store and fetched on demand by anything that needs them.

Three properties do most of the work.

**`Book`s are immutable.**
Once published, a `Book` never changes.
Fixing a mistake means publishing a new one.
A project that pins a version and edition gets identical bytes every time,
which is what makes an analysis reproducible.

**Versions and editions are separate.**
The version tracks the upstream data.
The edition tracks our processing of it.
Splitting them means a consumer can tell whether a change came from the data provider or from us.
That is usually the first question asked when a number moves.

**Metadata travels with the data.**
Each `Book` carries its licence as an SPDX identifier,
and a SHA256 hash for every resource.
The `Volume` above it carries the authors and the publisher.
Hashes are checked on download,
so a truncated or tampered file fails loudly rather than quietly producing wrong numbers.

## Why timeseries come in two shapes

Wide form has one row per timeseries and one column per year.
That is what [scmdata](https://scmdata.readthedocs.io/) expects,
and it is compact for climate model work.
Long form, with one row per observation, is what dataframe and database tooling expects.

A `Resource` is written in whichever shape produced it,
and the SDK converts between the two on read.
Asking for the wrong shape costs a reshape rather than an error,
so a producer does not have to guess what its consumers will want.

## Why the notebooks are moving out

The notebooks in this repository were originally the only way to build a `Book`.
That coupled every dataset's release cycle to this package's release cycle.
A one line fix to a single dataset meant a new release of `bookshelf`.

Datasets now live in their own feedstock repositories,
scaffolded from a [copier template](https://github.com/climate-resource/copier-bookshelf-dataset).
Each one releases on its own schedule and depends on `bookshelf` like any other user.
The notebooks that remain here are being migrated out.

## Why the SDK talks to an API

Earlier versions read and wrote a public S3 bucket directly.
That left several things unsolved.
Publishing updated the volume metadata without any locking,
so two people publishing the same volume at once could lose one of the updates.
Access control was whatever the bucket provided,
which meant the `private` flag hid a version from listings without protecting it.
There was also no way to discover a volume without already knowing its name.

The SDK talks to the Bookshelf API instead.
Registration is transactional,
so a partial publish fails as a whole rather than leaving a volume half updated.
Authorisation is carried by a token bound to an organisation,
so private data is genuinely private.
Discovery is a query rather than a guess.
