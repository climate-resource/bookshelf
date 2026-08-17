# Examples

Each directory here is a miniature feedstock and its expected results.

## The examples

| Example                               | What it proves                                                              |
| ------------------------------------- | --------------------------------------------------------------------------- |
| [`simple`](simple/)                   | The smallest legal recipe. One frame built inline, no inputs, no network.   |
| [`checked-in-data`](checked-in-data/) | A resource addressed by `path:` rather than `uri:`, hashed by the recorder. |
| [`multi-version`](multi-version/)     | One recipe, several upstream versions, selected by `--version`.             |

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
Upgrading `pyarrow` will result in differences to `writer.pyarrow`, whi

## What the runner pins

`code_ref`, `runner` and `activity_id` vary by machine, by working tree and by commit,
so the runner replaces them with fixed values before comparing.
Without that, every developer's goldens would differ and every commit would move them.
The book's `processing` fingerprint is the activity's, so it is pinned the same way.

The two executed-document resources are excluded.
Their bytes come from nbconvert, whose HTML is not stable across template versions,
so a golden over them would pin a rendering dependency rather than the bundle format.
