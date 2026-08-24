# Bookshelf Python SDK

The `bookshelf` package is the official Python SDK
for the Bookshelf data platform.
It provides synchronous and asynchronous facades
for consuming published data,
producing managed resources,
and running record and replay publishing workflows.

This migration replaces the legacy Bookshelf consumer library
and the separate `bookshelf-producer` distribution.

## Install

```bash
uv add bookshelf
```

The SDK requires Python 3.12 or newer.
Optional dataframe,
SCMRun,
and publishing integrations are available as extras:

```bash
uv add "bookshelf[dataframes,scmrun,publish]"
```

Continue with [Getting started](getting_started.md),
or browse the [API reference](api/).
