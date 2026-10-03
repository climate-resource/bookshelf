# Bookshelf

`bookshelf` is the official Python SDK for the Bookshelf data platform.
It supports synchronous and asynchronous data access,
managed resource publishing, record and replay workflows, and command line authentication and discovery.

[![PyPI](https://img.shields.io/pypi/v/bookshelf.svg)](https://pypi.org/project/bookshelf/)
[![Python](https://img.shields.io/pypi/pyversions/bookshelf.svg)](https://pypi.org/project/bookshelf/)
[![CI](https://github.com/climate-resource/bookshelf/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/climate-resource/bookshelf/actions/workflows/ci.yaml)
[![Licence](https://img.shields.io/pypi/l/bookshelf?label=licence)](https://github.com/climate-resource/bookshelf/blob/main/LICENSE)

## Installation

Install the SDK from PyPI:

```bash
uv add bookshelf
```

The SDK requires Python 3.12 or newer.
It ships with pandas and PyArrow, so `as_df()` and `as_arrow()` work out of the box.
`as_polars()` uses Polars if you have it installed.

Install optional integrations as needed:

```bash
uv add "bookshelf[scmrun,publish]"
```

## Example

```python
from bookshelf import Bookshelf

with Bookshelf() as bs:
    entry = bs.book("rcmip-emissions", "v5.1.0")["magicc"]
    frame = entry.as_df(year_min=2020, year_max=2100)
```

See the [package README](packages/bookshelf/README.md) for consuming,
publishing and authentication,
and the [documentation](https://climate-resource.github.io/bookshelf/latest/) for the rest.

## Minting tracking ids

Use `bookshelf.uuid7()` to generate a tracking id before writing a resource,
for example to store the id in a Zarr store's attributes:

```python
from bookshelf import uuid7

tracking_id = uuid7()
# Store str(tracking_id) in the data, then pass tracking_id=tracking_id when registering it.
```

The function returns a `uuid.UUID` with RFC 9562 version 7 bits.
Ids generated within the same millisecond have no additional ordering guarantee.

## Development

```bash
make virtual-environment
make test
make checks
```

See [docs/development.md](docs/development.md) for the bundle goldens,
strict type checking, and regenerating the model core.
