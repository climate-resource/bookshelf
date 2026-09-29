# Bookshelf Python SDK

The `bookshelf` package is the official Python SDK for the Bookshelf data platform.
It provides synchronous and asynchronous facades
for consuming published data,
producing managed resources,
and running record and replay publishing workflows.

Bookshelf 1.0 replaces the legacy Bookshelf consumer library
and the separate `bookshelf-producer` distribution.
Code written against 0.4 can follow [Migrating from 0.4](migrating.md).

## Install

```bash
uv add bookshelf
```

The SDK requires Python 3.12 or newer.
It ships with pandas and PyArrow, so `as_df()` and `as_arrow()` work out of the box.
`as_polars()` uses Polars if you have it installed.
SCMRun, figure (matplotlib) and publishing integrations are available as extras:

```bash
uv add "bookshelf[scmrun,figures,publish]"
```

Continue with [Getting started](getting_started.md),
or browse the [API reference](api/index.md).
