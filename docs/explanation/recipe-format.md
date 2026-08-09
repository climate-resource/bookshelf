# The recipe format

A feedstock's recipe sits alongside a build script,
and states the volume, the build, and each release the feedstock can produce.
`bookshelf record --version` picks one of those releases and records it.

The aim is to collect the metadata for the books in a single location.
This makes it easier to reason about and simplifies the build scripts.

## Example

Below is an example excerpt for PRIMAP-hist.

```yaml
volume:
  name: primap-hist
  license: CC-BY-NC            # Default licence for every release
  maintainers:
    - name: Jared Lewis
      email: jared.lewis@climate-resource.com
  topics: [emissions, inventories]
  keywords: [ghg, national]
  update_cadence: annual
  discovery:                   # volume-level defaults, overridable per release
    title: PRIMAP-hist
    abstract: National greenhouse gas emissions.
    publisher: Potsdam Institute for Climate Impact Research
    homepage_url: https://www.pik-potsdam.de/paris-reality-check/primap-hist/
    methodology_url: https://essd.copernicus.org/articles/17/3873/2025/

build:
  notebook: build.py
  visibility: public

releases:
  "v2.7":                      # a quoted string key, always
    doi: 10.5281/zenodo.17090760
    source_release_date: 2025-08-22
    description: Adds 2023, revises the third-party gap filling.
    license: CC-BY             # overrides the volume default for this release
    publisher: Climate Resource
    release_url: https://zenodo.org/records/17090760
    authors:
      - name: Jared Lewis
        email: jared.lewis@climate-resource.com
    resources:
      raw:
        type: tabular           # tabular, timeseries
        uri: https://zenodo.org/api/records/17090760/files/data.csv/content
        sha256: 77834f5f16197a463fe3df7e0eb3adda62a9e48355c9481926133986e35a9019
```

### What lives where

`volume:` holds what is true of the dataset whichever release is being built.
`name` is the slug and cannot change.
Everything else there can change.

`topics` and `keywords` are used for volume searches,
so they are declared once rather than per release.
Letting them vary would make a filter return a different volume
depending on which edition happened to match.
The other volume metadata will be rolled up and used for searching.
The mechanism for this will need some work to make something intuiative.

`volume.discovery:` holds the catalogue metadata a release may override.
The effective value is the volume's default plus the release's override,
resolved when the release is recorded and baked onto the book.

This split matters in practice.
The PRIMAP citation is dated and its publisher has moved between organisations over the years,
so neither can be a volume fact,
and a book keeps the metadata it was published with.

`releases:` holds one entry per upstream version.
A release may override any discovery field, and it declares its own `resources`.

`build.visibility:` is the tier the recorded book takes,
and it becomes the default for every resource the build records.
It sits under `build:` because it is a property of what a build publishes
rather than of the volume's identity.
The same volume can hold a hidden book and a public one.

Nothing in the recipe describes the data itself.
`spatial_coverage`, `temporal_coverage`, `variables`, `units`, `scenarios` and `frequency`
are computed per resource by the platform and rolled up.
`edition`, `tracking_id` and the storage path are assigned by the server.

## The rules

- **Release keys are quoted strings.**
  An unquoted `2.6` is a YAML float, and `2.70` would then collide with `2.7`.
- **Every release resolves a licence**,
  from `volume.license` or from its own `license` override.
  A recipe where some release would resolve neither does not load,
  whichever release is being built.
- **Releases do not inherit from each other.**
  Each restates its sources in full.
  There is no `extends` and no carry-forward from the previous release.
- **Sources are optional.**
  A build that constructs its frame inline declares none.
- **A source has `uri:` or `path:`, and not both.**
  `uri:` is remote and carries the `sha256` the fetch is checked against.
  `path:` is a file beside the recipe, and its digest is computed when it is read.
- **A source always declares its `type`**, which is never inferred from the file extension.
- **Unknown keys are an error at every level**, so a typo is never silently dropped.
- **Releases are ordered by the recipe**, in the order the mapping states them.
  Each resolved release carries its position, so nothing has to parse a version string to sort.

## The version

`--version` is required on `bookshelf record`,
and it is the only place a version is stated.
A build file therefore calls `bookshelf.setup()` without naming a version:

```python
import bookshelf

bs, book = bookshelf.setup()
```

Backfilling an older release is the same command with an older version.

A version the recipe does not define is refused, and the message names the ones it does define.
`-p KEY=VALUE` is unchanged and remains for genuine build parameters.
The version is not one of them and never reaches the build as a global.

## The edition

The edition is determined by the server which is why it isn't included in the recipe.
It advances when the data changes, and the latest edition may differ between books.

## The build script

With the recipe carrying the facts, the build file keeps only the processing:

```python
bs, book = bookshelf.setup()          # the version comes from --version
raw = bs.source("raw")                # fetched from a DOI, verified against the declared sha256, registered

data = pd.read_csv(raw.path)
...
book.write("by_country", by_country, used=[raw])
book.write("by_region", by_region, used=[raw])
```

`.source` and `.write` used here are a convienience wrapper on top of the lower level `activity` primatives.
For our simple feedstocks this will make it easier to understand,
while preserving the lower level functionality for more complex workflows.
