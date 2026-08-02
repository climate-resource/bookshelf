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
Reproducing a result from a year ago means reconstructing whatever the cleaning
code did at the time.

`bookshelf` exists to pay that cost once.

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
Splitting them means a consumer can tell whether a change came from the data provider
or from us, which is usually the first question asked when a number moves.

**Metadata travels with the data.**
Each `Book` is a
[datapackage](https://specs.frictionlessdata.io/data-package/)
recording the licence, the source, the author and the hash of every file.
The hashes are checked on download,
so a truncated or tampered file fails loudly rather than quietly producing wrong numbers.

## Why a datapackage

We did not want to invent a metadata format.
The frictionless
[data package](https://specs.frictionlessdata.io/data-package/)
specification already covers resources, hashes, licences and schemas,
and it has tooling in several languages.
A `Book` is a datapackage with a few extra fields,
so a `Book` can be read by anything that already understands datapackages.

## Why timeseries are stored in two shapes

Most `Resource`s are timeseries, written in both wide and long form.

Wide form has one row per timeseries and one column per year.
It is what [scmdata](https://scmdata.readthedocs.io/) expects,
and it is compact for climate model work.

Long form has one row per observation.
It is what dataframe and database tooling expects,
and it is much easier to join against other tables.

Writing both costs a little storage and saves every consumer a reshape.

## Why the notebooks are moving out

The notebooks in this repository were originally the only way to build a `Book`.
That coupled every dataset's release cycle to this package's release cycle.
A one line fix to a single dataset meant a new release of `bookshelf`.

Datasets now live in their own feedstock repositories, scaffolded from a
[copier template](https://github.com/climate-resource/copier-bookshelf-dataset).
Each one releases on its own schedule and depends on `bookshelf` like any other user.
The notebooks that remain here are kept as examples and as test fixtures.

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
