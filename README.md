# Bookshelf

`bookshelf` is the official Python SDK for the Bookshelf data platform.
It supports synchronous and asynchronous data access,
managed resource publishing, record and replay workflows, and command line authentication and discovery.

[![PyPI](https://img.shields.io/pypi/v/bookshelf.svg)](https://pypi.org/project/bookshelf/)
[![Python](https://img.shields.io/pypi/pyversions/bookshelf.svg)](https://pypi.org/project/bookshelf/)
[![CI](https://github.com/climate-resource/bookshelf/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/climate-resource/bookshelf/actions/workflows/ci.yaml)
[![Licence](https://img.shields.io/pypi/l/bookshelf?label=licence)](https://github.com/climate-resource/bookshelf/blob/main/LICENCE)

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
    entry = bs.book("rcmip-emissions", "v5.1.0")["magicc"]
    frame = entry.as_df(year_min=2020, year_max=2100)
```

See the [package README](packages/bookshelf/README.md) for consuming,
publishing, authentication, and code generation.

## Development

```bash
make virtual-environment
make test
make checks
```

See [docs/development.md](docs/development.md) for the bundle goldens,
strict type checking, and regenerating the model core.
