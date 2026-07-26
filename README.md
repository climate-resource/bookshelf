# Bookshelf

`bookshelf` is the official Python SDK for the Bookshelf data platform.
It supports synchronous and asynchronous data access,
managed resource publishing,
record and replay workflows,
and command line authentication and discovery.

[![PyPI](https://img.shields.io/pypi/v/bookshelf.svg)](https://pypi.org/project/bookshelf/)
[![Python](https://img.shields.io/pypi/pyversions/bookshelf.svg)](https://pypi.org/project/bookshelf/)
[![CI](https://github.com/climate-resource/bookshelf/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/climate-resource/bookshelf/actions/workflows/ci.yaml)
[![Licence](https://img.shields.io/pypi/l/bookshelf?label=licence)](https://github.com/climate-resource/bookshelf/blob/main/LICENCE)

Version 1 replaces the legacy Bookshelf consumer library.
Applications that still depend on that library must pin `bookshelf<1`.
The retired `bookshelf-producer` distribution is not part of the version 1 workspace.
Its publishing capabilities now live in the `bookshelf` SDK.

## Installation

Install the SDK from PyPI:

```bash
uv add bookshelf
```

Install optional integrations as needed:

```bash
uv add "bookshelf[dataframes,scmrun,publish]"
```

The SDK requires Python 3.12 or newer.

## Example

```python
from bookshelf import Bookshelf

with Bookshelf() as bs:
    entry = bs.book("rcmip-emissions", "v5.1.0")["magicc-rcmip"]
    frame = entry.as_df(year_min=2020, year_max=2100)
```

See the [package README](packages/bookshelf/README.md) for consuming,
publishing,
authentication,
code generation,
and development instructions.

## Development

Install the locked workspace and run its checks:

```bash
uv sync --python 3.12 --all-extras --dev --locked
make test
uv run ruff check packages/bookshelf
uv run ruff format --check packages/bookshelf
```
