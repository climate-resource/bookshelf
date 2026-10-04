# Development

The repository is a uv workspace
with one published distribution under `packages/bookshelf`.
Python 3.12 or newer is required.

Set up the environment and the pre-commit hooks:

```bash
make virtual-environment
```

Run the checks and the tests the way CI does:

```bash
make checks
make test
```

`make checks` runs pre-commit (ruff and the other hooks) and then strict type checking.
Run mypy from `packages/bookshelf`, so its nested configuration applies.

Keep `--group test` on any direct pytest run.
It carries pytest-asyncio, and without it every async test is skipped while the suite still passes.

## Bundle goldens

`packages/bookshelf/tests/test_bundle_golden.py` records a fixture build
and compares the resulting manifest byte for byte
against the golden files under `packages/bookshelf/tests/golden/simple/`.
Every other test asserts on parsed objects,
so this is what catches a renamed field, a dropped key or a reordered list.

A failing golden means the recorded bytes changed.
Read the diff before accepting it.
When the change is intended, regenerate rather than hand-edit:

```bash
make test-golden-update
```

The regenerated files then land as a reviewable diff
in the same commit as the change that caused them.

A pyarrow upgrade changes the parquet bytes and so changes the recorded hashes.
It shows up in the golden as a changed `writer.pyarrow` next to those hashes,
so the cause is visible in the diff.

## Generated model core

Generated models and the generated client come from the vendored OpenAPI contract
at `packages/bookshelf/openapi.json`.
Refresh that snapshot explicitly when the platform contract changes,
then regenerate and review the model diff in the same change.
Do not edit the generated files by hand.
Regenerate and review them with:

```bash
uv run --project packages/bookshelf --locked --group codegen \
  python packages/bookshelf/scripts/generate_models.py
uv run --project packages/bookshelf --locked \
  python packages/bookshelf/scripts/generate_client.py
```

CI runs both and fails when either leaves a diff.

## Building the distribution

Build the sdist and wheel, then install the wheel into a scratch environment:

```bash
uv build --package bookshelf --out-dir /tmp/bookshelf-dist
uv pip install /tmp/bookshelf-dist/bookshelf-*.whl
```

The sdist carries the source and the licence, not the tests.
The public test suite uses local transports and fixtures.
Backend contract tests live with the platform.
