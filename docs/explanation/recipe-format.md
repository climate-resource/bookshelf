# The recipe format

A feedstock's recipe sits alongside a build script,
and states the volume, the build, and each version the feedstock can produce.
`bookshelf record --version` picks one of those versions and records it.

The aim is to collect the metadata for the books in a single location.
This makes it easier to reason about and simplifies the build scripts.

## Example

Below is an example excerpt for PRIMAP-hist.

```yaml
volume:
  name: primap-hist
  maintainers:
    - name: Jared Lewis
      email: jared.lewis@climate-resource.com
  topics: [emissions, inventories]
  keywords: [ghg, national]
  update_cadence: annual
  # deprecated: true                       # the volume is no longer maintained
  # superseded_by: primap-hist-v3          # the slug that replaces it
  # deprecation_note: Replaced by v3.
  discovery:                               # volume-level defaults, overridable per version
    title: PRIMAP-hist
    abstract: National greenhouse gas emissions.
    publisher: Potsdam Institute for Climate Impact Research
    homepage_url: https://www.pik-potsdam.de/paris-reality-check/primap-hist/
    methodology_url: https://essd.copernicus.org/articles/17/3873/2025/

build:
  notebook: build.py

versions:
  "v2.7":                      # a quoted string key, always
    doi: 10.5281/zenodo.17090760
    release_date: 2025-08-22
    description: Adds 2023, revises the third-party gap filling.
    license: CC-BY             # Required for each version
    visibility: public         # optional, and hidden when it is left out
    publisher: Climate Resource
    release_url: https://zenodo.org/records/17090760
    authors:
      - name: Jared Lewis
        email: jared.lewis@climate-resource.com
    resources:
      raw:
        type: tabular
        uri: https://zenodo.org/api/records/17090760/files/data.csv/content
        sha256: 77834f5f16197a463fe3df7e0eb3adda62a9e48355c9481926133986e35a9019
```

### What lives where

A recipe declares only the resources a build reads.
The resources a build writes are named by `book.write`, and never appear here.

| Section               | Holds                                          | Changes per version?   |
| --------------------- | ---------------------------------------------- | ---------------------- |
| `volume:`             | identity and search vocabulary                 | no                     |
| `volume.discovery:`   | catalogue defaults                             | overridable            |
| `build:`              | how it is built                                | no                     |
| `versions.<version>:` | one upstream version, its terms and resources  | yes                    |
| computed              | coverage, variables, units, frequency, edition | assigned by the server |

`volume.name` is the slug and cannot change.
Everything else in `volume:` can.

`topics` and `keywords` are declared once because they drive volume search.
Letting them vary would make a filter return a different volume
depending on which edition happened to match.

A version may override any `discovery` field.
The effective value is the volume's default plus the version's override,
resolved when the version is recorded and baked onto the book.
Previous editions of the same upstream version may have different metadata.

`visibility` is the tier the recorded book takes, and the default every resource it writes takes.
An embargoed version sitting alongside published ones is ordinary,
so the same volume can hold a hidden book and a public one.
Leaving it out means `hidden`.
That is why it is optional where `license` is required.

Nothing in the recipe describes the data itself.
`spatial_coverage`, `temporal_coverage`, `variables`, `units`, `scenarios` and `frequency`
are computed per resource by the platform and rolled up.
`edition`, `tracking_id` and the storage path are assigned by the server.

### The discovery fields

Every field below is optional, and every one may be set on the volume, on a version, or on both.
Where both set it, the version wins.

| Field               | Meaning                                                         |
| ------------------- | --------------------------------------------------------------- |
| `title`             | The human readable name of the dataset.                         |
| `abstract`          | A short summary of what the dataset covers.                     |
| `description`       | A longer note, typically what changed in this version.          |
| `publisher`         | The organisation that published the data.                       |
| `publisher_url`     | The publisher's homepage.                                       |
| `authors`           | Who to credit, as a list of name, email, affiliation and orcid. |
| `citation`          | The citation to use, as the publisher states it.                |
| `doi`               | The upstream DOI for this version.                              |
| `release_date`      | The date upstream published it.                                 |
| `release_url`       | The page for this particular version.                           |
| `homepage_url`      | The dataset's landing page.                                     |
| `documentation_url` | Where the dataset is documented.                                |
| `methodology_url`   | The paper or note describing how it was produced.               |
| `repository_url`    | The code that produces the dataset upstream.                    |
| `license_url`       | The full licence text.                                          |
| `intended_uses`     | What the data is suitable for.                                  |
| `limitations`       | What it is not suitable for, and known caveats.                 |

## The rules

- **Version keys are quoted strings.**
  An unquoted `2.6` is a YAML float, and `2.70` would then collide with `2.7`.
- **Every version states its own `license`.**
  The terms a book is published under matter too much to be inferred,
  and a relicensed version is common enough that a volume-level default
  would let one go out under the wrong terms without anyone having written it down.
- **A version states its own `visibility`, or it is hidden.**
  There is no volume-level or build-level default,
  so one version can be embargoed while the rest stay public.
- **Versions do not inherit from each other.**
  Each restates its resources in full.
  There is no `extends` and no carry-forward from the previous version.
- **Resources are optional.**
  A build that constructs its frame inline declares none.
- **A resource has `uri:` or `path:`, and not both.**
  `uri:` is remote and carries the `sha256` the fetch is checked against.
  `path:` is a file beside the recipe, and its digest is computed when it is read.
- **A resource always declares its `type`**, which is never inferred from the file extension.
- **Unknown keys are an error at every level**, so a typo is never silently dropped.
- **Versions are ordered by the recipe**, in the order the mapping states them.
  Each resolved version carries its position, so nothing has to parse a version string to sort.

## The version

An explicit `--version` is required on `bookshelf record/publish`,
instead of inferring the most recent.

Backfilling an older version is the same command with an older version.

## The edition

The edition is determined by the server which is why it isn't included in the recipe.
It advances when the data changes, and the latest edition may differ between books.

## The build script

With the recipe carrying the facts, the build file keeps only the processing:

```python
bs, book = bookshelf.setup()          # the version comes from --version
raw = bs.resource("raw")              # fetched, verified against the declared sha256, registered

data = pd.read_csv(raw.path)
...
book.write("by_country", by_country, used=[raw])
book.write("by_region", by_region, used=[raw])
```

`.resource` and `.write` used here are a convenience wrapper on top of the lower level `activity` primitives.
For our simple feedstocks this will make it easier to understand,
while preserving the lower level functionality for more complex workflows.

## Open questions

- Volume metadata beyond `topics` and `keywords` is meant to roll up into search.
  The mechanism is not designed yet.
- `resource.type` is a free string today.
  It should be `models.ResourceType`, which is the enum the platform already registers against.
- Does changing the discovery information trigger a new edition?
  Its pretty much free as we dedupicate data
