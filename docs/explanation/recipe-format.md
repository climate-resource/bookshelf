# The recipe format

A feedstock's recipe sits alongside a build script,
and states the volume, what every book defaults to, the build,
and each book the feedstock can produce.
`bookshelf record --version` picks one of those books and records it.

The aim is to collect the metadata for the books in a single location.
This makes it easier to reason about and simplifies the build scripts.

The sections are named after the domain model,
so a recipe reads in the same words the platform uses: a volume holds books,
and a book holds resources.

## Example

Below is an example excerpt for PRIMAP-hist.

```yaml
volume:
  name: primap-hist
  maintainers:
    - name: Jared Lewis
      email: jared.lewis@climate-resource.com
  keywords: [ghg, national, emissions]
  update_cadence: annual
  # deprecated: true                       # the volume is no longer maintained
  # superseded_by: primap-hist-v3          # the slug that replaces it
  # deprecation_note: Replaced by v3.

defaults:                                  # what every book starts from
  title: PRIMAP-hist
  abstract: National greenhouse gas emissions.
  publisher: Potsdam Institute for Climate Impact Research
  homepage_url: https://www.pik-potsdam.de/paris-reality-check/primap-hist/
  methodology_url: https://essd.copernicus.org/articles/17/3873/2025/
  authors:
    - name: Gütschow, J.
    - name: Busch, D.
    - name: Pflüger, M.
      email: ...
  # visibility: hidden                     # optional, and hidden when it is left out
  resources:
    raw:
      type: tabular                        # the type does not move between books

build:
  notebook: build.py

books:
  - version: "v2.7"            # a quoted string, always, and unique across the books
    doi: 10.5281/zenodo.17090760
    release_date: 2025-08-22
    description: Adds 2023, revises the third-party gap filling.
    license: CC-BY
    visibility: public
    publisher: Climate Resource
    release_url: https://zenodo.org/records/17090760
    resources:
      raw:                     # type comes from defaults
        uri: https://zenodo.org/api/records/17090760/files/data.csv/content
        sha256: 77834f5f16197a463fe3df7e0eb3adda62a9e48355c9481926133986e35a9019
  - version: "v2.8_beta1"
    description: Adds 2025 data. Preview version of the data.
    license: Unreleased
    visibility: hidden
    resources:
      raw:                     # type comes from defaults
        uri: file:///../PRIMAP-hist_data/[...]
        sha256: "[...]"
```

### What lives where

A recipe declares only the resources a build reads.
The resources a build writes are named by `book.write`, and never appear here.

| Section               | Holds                                          | Changes per book?      |
| --------------------- | ---------------------------------------------- | ---------------------- |
| `build:`              | how it is built                                | no                     |
| `volume:`             | identity and search vocabulary                 | no                     |
| `defaults:`           | what every book starts from                    | overridable            |
| `books[]`             | one book, its terms and its resources          | yes                    |
| computed              | coverage, variables, units, frequency, edition | assigned by the server |

`volume.name` is the slug and cannot change.
Everything else in `volume:` can.

`keywords` is declared once because it doesn't change between books.
Letting it vary would make a filter return a different volume
depending on which edition happened to match.
Changes to the volume metadata are updated on the next publish.

A book may override anything under `defaults:`.
The merge is field by field rather than section by section,
so stating one discovery field on a book keeps the rest of the defaults.
The fields sit flat at both levels, so `defaults:` and a book entry read the same way.
The effective value is resolved when the book is recorded and baked onto it,
which is why previous editions of the same upstream version may carry different metadata.

`visibility` is the tier the recorded book takes, and the default every resource it writes takes.
An embargo usually covers a whole feedstock, so it is stated once under `defaults:`,
and a book that lifts it says so.
Where neither states it the book is `hidden`.
That is why it is optional where `license` is required.

Nothing in the recipe describes the data itself.
`spatial_coverage`, `temporal_coverage`, `variables`, `units`, `scenarios` and `frequency`
are computed per resource by the platform and rolled up.
`edition`, `tracking_id` and the storage path are assigned by the server.

### The discovery fields

Every field below is optional, and every one may be set under `defaults:`, on a book, or on both.
They sit flat at both levels, and where both set it, the book wins.

| Field               | Meaning                                                         |
| ------------------- | --------------------------------------------------------------- |
| `title`             | The human readable name of the dataset.                         |
| `abstract`          | A short summary of what the dataset covers.                     |
| `description`       | A longer note, typically what changed in this book.             |
| `publisher`         | The organisation that published the data.                       |
| `publisher_url`     | The publisher's homepage.                                       |
| `authors`           | Who to credit, as a list of name, email, affiliation and orcid. |
| `citation`          | The citation to use, as the publisher states it.                |
| `doi`               | The upstream DOI for this book.                                 |
| `release_date`      | The date upstream published it.                                 |
| `release_url`       | The page for this particular release.                           |
| `homepage_url`      | The dataset's landing page.                                     |
| `documentation_url` | Where the dataset is documented.                                |
| `methodology_url`   | The paper or note describing how it was produced.               |
| `repository_url`    | The code that produces the dataset upstream.                    |
| `license_url`       | The full licence text.                                          |
| `intended_uses`     | What the data is suitable for.                                  |
| `limitations`       | What it is not suitable for, and known caveats.                 |

## The rules

- **`books:` is a list, and every book states a quoted `version:`.**
  An unquoted `2.6` is a YAML float, and `2.70` would then collide with `2.7`.
  A version names one book, so two books claiming the same one are rejected.
- **Every book states its own `license`.**
  The terms a book is published under matter too much to be inferred,
  and a relicensed version is common enough that a default
  would let one go out under the wrong terms without anyone having written it down.
- **A book takes its `visibility` from itself, then from `defaults:`, then `hidden`.**
  So one book can be embargoed while the rest stay public,
  and a feedstock that is hidden as a whole says so once.
- **Books do not inherit from each other.**
  A book inherits from `defaults:` and from nowhere else.
  There is no `extends` and no carry-forward from the book before it,
  so a reader never has to walk backwards through the file.
- **Resources are optional.**
  A build that constructs its frame inline declares none.
- **A resource default is a template, not an addition.**
  A book that never names the resource does not get it,
  because a default that could add one would hide what a book reads from the book itself.
- **A book's location replaces the default's.**
  Stating `path:` or `uri:` on a book drops the default's `uri:`, `path:` and `sha256:`,
  so a default location never sits beside a book's and trips the one-location rule.
- **A resource has `uri:` or `path:`, and not both.**
  `uri:` is remote and carries the `sha256` the fetch is checked against.
  `path:` is a file beside the recipe, and its digest is computed when it is read.
  This is asked of the merged resource, so a default and a book may each hold half of it.
- **A resource always declares its `type`**, which is never inferred from the file extension.
  It is one of `tabular`, `timeseries`, `geospatial`, `document` or `binary`,
  the same set the platform registers a resource under,
  so a recipe that loads cannot name a type registration would refuse.
  This is the field that usually belongs under `defaults:`, because it does not move between books.
- **Unknown keys are an error at every level**, so a typo is never silently dropped.
- **Books are ordered by the recipe**, in the order the list states them.
  Each resolved book carries its position, so nothing has to parse a version string to sort.

## Versioning

The bookshelf uses a composite versioning format to support a variaty of different use-cases.
This flexibility can also be a bit confusing as it can be interpreted in a few different ways.

### The version

This is the part of the version string that can be controlled.
The version should refer to the upstream release of a dataset if applicable.

### The edition

The edition is an auto-incrementing integer for each time a version is reprocessed.
The value is determined by the server which is why it isn't included in the recipe.
It advances when the data changes so the latest edition may differ between books and the exact value mean anything.

Publishing the a unchanged book is idempotent resulting in an unchanged edition.

## The build script

With the recipe carrying the facts, the build file keeps only the processing:

```python
bs, book = bookshelf.setup()          # the version comes from --version
raw = bs.use("raw")                   # fetched, verified against the declared sha256, registered

data = pd.read_csv(raw.path)
...
book.write("by_country", by_country, used=[raw])
book.write("by_region", by_region, used=[raw])
```

`.use` and `.write` used here are a convenience wrapper on top of the lower level `activity` primitives.
For our simple feedstocks this will make it easier to understand,
while preserving the lower level functionality for more complex workflows.

## Open questions

- Volume metadata beyond `keywords` is meant to roll up into search.
  The mechanism is not designed yet.
- Does changing the discovery information trigger a new edition?
  Its pretty much free as we dedupicate data
