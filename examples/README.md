# Examples

Each directory here is a miniature feedstock and its expected results.

Most are a `bookshelf.yaml` recipe with a build file, which is what `bookshelf record` drives.
One is a plain `record.py` script that records for itself, for a pipeline that publishing is only a
small part of.

## The examples

| Example                               | What it proves                                                              |
| ------------------------------------- | --------------------------------------------------------------------------- |
| [`simple`](simple/)                   | The smallest legal recipe. One frame built inline, no inputs, no network.   |
| [`checked-in-data`](checked-in-data/) | A resource addressed by `path:` rather than `uri:`, hashed by the recorder. |
| [`multi-version`](multi-version/)     | One recipe, several upstream versions, selected by `--version`.             |
| [`complex-processing`](complex-processing/) | Several outputs and a real `used=` graph across steps. |
| [`defaults-and-overrides`](defaults-and-overrides/) | Inheriting from `defaults:`, then overriding some. |
| [`figures`](figures/) | A png attached as a document entry, with no data dictionary. |
| [`mixed-visibility`](mixed-visibility/) | A public book carrying one hidden resource. |
| [`resource-attribution`](resource-attribution/) | Per-resource authors and licence, where the input and the output differ. |
| [`reissue`](reissue/) | Same version, changed processing, which sits outside the seal. |
| [`fetch-from-web`](fetch-from-web/) | One upstream url, digest verified and cached. Needs the network. |
| [`low-level-api`](low-level-api/) | A plain script that records for itself, with no recipe and no recorder. |

Two more are wanted and cannot be written yet, because the SDK has no way to express them.

- A pure catalogue run, recording resources and no book.
  `bookshelf.setup` under a recording always drafts a book, and a build file that never calls it
  is refused, so no bookless bundle can be recorded.
- A book derived from a published book, so the lineage crosses volumes.
  A `bookshelf://` resource registers nothing, and `used=` cites only what the same bundle records,
  so the edge is refused when the build is recorded.

## Running them

```bash
python examples/run_all.py
```

It records every book each recipe declares into a scratch directory, asserts the bundle is valid,
and compares the manifest bytes and the resource filenames against `expected/`.
It exits non-zero if any example fails, which is what makes it usable as a CI gate.
`make test` covers the same ground through `packages/bookshelf/tests/test_examples.py`.

Run one example with `--example simple`.

## Network examples

An example needs the network when any of its books declares a resource with a `uri:`.
The runner reads that from the recipe rather than from a separate declaration, so the two can never fall out of step.
Such examples are skipped by default and run with `--network`.

The golden comparison does not hit the network.
A fetch is served from the local cache, so a genuine upstream change surfaces as a digest failure rather than as a golden diff.
Refreshing a golden is never the fix for an upstream content change.

## Refreshing a golden

```bash
UPDATE_BUNDLE_GOLDENS=1 python examples/run_all.py
```

That is the same switch `make test-golden-update` uses for the bundle golden, because one repository
gets one way to refresh a golden.
`--update-golden` is an alias for the variable and nothing more.

Read the regenerated `manifest.lock` before committing it.
Upgrading `pyarrow` will result in differences to `writer.pyarrow`,
which is a dependency moving rather than the bundle format moving.

## What the runner pins

`code_ref`, `runner` and `activity_id` vary by machine, by working tree and by commit,
so the runner replaces them with fixed values before comparing.
Without that, every developer's goldens would differ and every commit would move them.
The book's `processing` fingerprint is the activity's, so it is pinned the same way.

The two executed-document resources are excluded.
Their bytes come from nbconvert, whose HTML is not stable across template versions,
so a golden over them would pin a rendering dependency rather than the bundle format.
