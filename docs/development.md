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

Generated models come from the vendored OpenAPI contract.
Do not edit them by hand.
Regenerate and review them with:

```bash
uv run --python 3.12 --project packages/bookshelf --locked --group codegen \
  python packages/bookshelf/scripts/generate_models.py
```
