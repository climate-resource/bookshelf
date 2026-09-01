# Keeping pinned books up to date with Renovate

A feedstock that builds on published data pins the exact edition it read,
so every run sees the same bytes:

```yaml
resources:
  primap:
    uri: bookshelf://primap-hist/v2.7_e002/by_country
```

The pin is the right default, but it goes stale silently:
nothing in the repository says a `v2.8` or a corrected `v2.7_e003` now exists.

[Renovate](https://docs.renovatebot.com) can watch those pins the same way it watches
`pyproject.toml`, and open a pull request when a newer coordinate is published.
The platform serves a release feed per volume
(`GET /v1/volumes/{volume}/releases`)
in exactly the shape Renovate's
[custom datasource](https://docs.renovatebot.com/modules/datasource/custom/) reads,
and a shared preset wires it all up.

## Set up the repository

Add the preset to the repository's `renovate.json`
(create the file if the repository has none):

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": [
    "config:best-practices",
    "github>climate-resource/bookshelf-platform//renovate/bookshelf"
  ]
}
```

That is the whole setup for a repository Renovate already runs on.

## The pin shapes Renovate recognises

**Recipe references** in any YAML file, pinned to an edition:

```yaml
resources:
  primap:
    uri: bookshelf://primap-hist/v2.7_e002/by_country
```

A reference that names no edition (`bookshelf://primap-hist/v2.7`)
already floats to the newest edition on the platform,
so Renovate deliberately leaves it alone.

**Coordinates pinned in Python**, for code that calls the SDK directly.
The comment names the volume, and the next assignment holds the coordinate:

```python
# renovate: bookshelf-volume=primap-hist
PRIMAP_BOOK = "v2.7_e002"

version, _, edition = PRIMAP_BOOK.partition("_e")
book = shelf.book("primap-hist", version, edition=int(edition))
```

## A worked example

A feedstock that downscales PRIMAP data might look like:

```
my-feedstock/
├── bookshelf.yaml
├── build.py
└── renovate.json
```

`bookshelf.yaml` pins the upstream book:

```yaml
volume:
  name: primap-downscaled

defaults:
  title: PRIMAP-hist, downscaled

build:
  notebook: build.py

books:
  - version: "v1.2.0"
    license: CC-BY-4.0
    visibility: public
    resources:
      primap:
        uri: bookshelf://primap-hist/v2.7_e002/by_country
```

When `primap-hist` publishes `v2.7_e003`,
Renovate opens a pull request titled along the lines of
"Update bookshelf book primap-hist to v2.7_e003",
whose whole diff is the coordinate:

```diff
-        uri: bookshelf://primap-hist/v2.7_e002/by_country
+        uri: bookshelf://primap-hist/v2.7_e003/by_country
```

CI runs the feedstock against the new upstream edition,
and merging is the decision that the rebuild should happen.
The `version:` your own books declare is never touched:
only `bookshelf://` references and annotated pins are managed.

## Editions and versions are different update types

The preset maps a new version onto Renovate's usual major/minor/patch update types,
and a new edition of the same version onto the `build` type.
An edition is a reprocessing of the same upstream release,
so many repositories will want to take those automatically
while new versions wait for review:

```json
{
  "packageRules": [
    {
      "matchDatasources": ["custom.bookshelf"],
      "matchUpdateTypes": ["build"],
      "automerge": true
    }
  ]
}
```

## Limits

- Renovate calls the platform anonymously, so only public books appear in the feed.
  Pins on `org`-visibility books will not be updated.
- The preset's versioning orders labels shaped like `v1`, `v1.2` or `v1.2.3`
  (the `v` optional).
  A volume versioned another way (say `2024a`) is skipped rather than mis-ordered.
- The full pull-request behaviour
  (schedules, grouping, the datasource URL for a different platform instance)
  is documented beside the preset in the
  [bookshelf-platform repository](https://github.com/climate-resource/bookshelf-platform/blob/main/docs/renovate.md).
