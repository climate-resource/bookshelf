# The recipe format

A feedstock's recipe is what it declares once,
so that building a release is a command rather than a program.
It states the volume, the build, and each release the feedstock can produce.
`bookshelf record --version` picks one of those releases and records it.

The recipe holds no notion of a newest or current release.
The platform knows what is published, and the recipe does not restate it.

## The sections

```yaml
volume:
  name: primap-hist            # the slug, immutable
  license: CC-BY-NC            # the default for every release
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
    sources:
      raw:
        type: tabular
        uri: https://zenodo.org/api/records/17090760/files/data.csv/content
        sha256: 77834f5f16197a463fe3df7e0eb3adda62a9e48355c9481926133986e35a9019
```

### Which facts live where

`volume:` holds what is true of the dataset whichever release is being built.
`name` is the slug and cannot change. Everything else there can.
`topics` and `keywords` are the search vocabulary,
so they are declared once rather than per release.
Letting them vary would make a filter return a different volume
depending on which edition happened to match.

`volume.discovery:` holds the catalogue metadata a release may override.
The effective value is the volume's default plus the release's override,
resolved when the release is recorded and baked onto the book.
A publish never mutates the volume.
This split matters in practice.
The PRIMAP citation is dated and its publisher has moved between organisations over the years,
so neither can be a volume fact,
and a book keeps the metadata it was published with.

`releases:` holds one entry per upstream version.
A release may override any discovery field, and it declares its own `sources`.

Nothing in the recipe describes the data itself.
`spatial_coverage`, `temporal_coverage`, `variables`, `units`, `scenarios` and `frequency`
are computed per resource by the platform and rolled up.
`edition`, `tracking_id` and the storage path are assigned by the server.
Declaring any of them in a recipe would only let them go stale,
so each is an unknown key and therefore an error.

## Splitting the releases out

A recipe with many releases can keep `volume:` and `build:` in `bookshelf.yaml`
and put one file per release under `releases/`:

```
bookshelf.yaml
releases/
  v2.6.yaml
  v2.7.yaml
```

Each file holds exactly what that release's mapping value holds in the single-file form,
and the version is the file stem.
The two layouts load to the same recipe.
Using both at once is an error rather than a merge,
because merging would make the file that states a release depend on which one loaded first.

## The rules

- **Release keys are quoted strings.**
  An unquoted `2.6` is a YAML float, and `2.70` would then collide with `2.7`.
- **Releases do not inherit from each other.**
  Each restates its sources in full.
  There is no `extends` and no carry-forward, so reading one release tells the whole story.
- **Sources are optional.**
  A build that constructs its frame inline declares none.
- **A source has `uri:` or `path:`, and not both.**
  `uri:` is remote and carries the `sha256` the fetch is checked against.
  `path:` is a file beside the recipe, and its digest is computed when it is read.
- **A source always declares its `type`**, which is never inferred from the file extension.
- **Unknown keys are an error at every level**, so a typo is never silently dropped.
- **Releases are ordered by the recipe.**
  The single-file form uses its mapping order, and the split form uses sorted filenames.
  Each resolved release carries its position, so nothing has to parse a version string to sort.

## The version

`--version` is required on `bookshelf record`,
and it is the only place a version is stated.
There is no default in the recipe, so there is no second statement to disagree with it.
A build file therefore calls `bookshelf.setup()` without naming a version:

```python
import bookshelf

bs, book = bookshelf.setup()
```

Backfilling an older release is the same command with an older version.

A version the recipe does not define is refused, and the message names the ones it does define.
`-p KEY=VALUE` is unchanged and remains for genuine build parameters.
The version is not one of them and never reaches the build as a global.

## The build file this shape is heading towards

With the recipe carrying the facts, the build file keeps only the processing:

```python
bs, book = bookshelf.setup()          # the version comes from --version
raw = bs.source("raw")                # fetched, verified against the declared sha256, registered

data = pd.read_csv(raw.path)
...
book.write("by_country", by_country, used=[raw])
book.write("by_region", by_region, used=[raw])
```

The uuid derivations, hand rolled fetches, digest checks and version parameters
that build files carry today are recipe facts wearing Python clothes, and they all move out.
`bs.source()` and `book.write()` are not part of this change.
The recipe schema and the single `--version` entry point are what they will build on.
