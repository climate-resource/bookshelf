# Development

The repository is a uv workspace
with one published distribution under `packages/bookshelf`.
Python 3.12 or newer is required.

Install the locked SDK environment:

```bash
uv sync --python 3.12 --package bookshelf --all-extras --dev --locked
```

Run the validation suite:

```bash
uv run --python 3.12 --package bookshelf --all-extras pytest packages/bookshelf
uv run --python 3.12 ruff check packages/bookshelf
uv run --python 3.12 ruff format --check packages/bookshelf
```

Run strict type checking from the package directory,
so its nested configuration applies:

```bash
cd packages/bookshelf
uv run --python 3.12 --locked --all-extras mypy src
```

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

Generated models come from the vendored OpenAPI contract.
Do not edit them by hand.
Regenerate and review them with:

```bash
uv run --python 3.12 --project packages/bookshelf --locked --group codegen \
  python packages/bookshelf/scripts/generate_models.py
```
