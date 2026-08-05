# Bookshelf Python SDK

The `bookshelf` package is the official Python SDK for the Bookshelf data platform.
It provides synchronous and asynchronous facades for consuming published data,
producing managed resources,
and running record and replay publishing workflows.
It also includes the `bookshelf` command line interface for authentication,
discovery,
and local cache management.

This migration replaces the legacy Bookshelf consumer library.

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

For local development,
install the workspace package and all extras with the lock file enforced:

```bash
uv sync --locked --package bookshelf --all-extras
```

A local wheel can also be built and installed directly:

```bash
uv build --project packages/bookshelf --out-dir /tmp/bookshelf-sdk-dist
uv pip install /tmp/bookshelf-sdk-dist/bookshelf-*.whl
```

## Consuming published data

The `bookshelf` package provides synchronous and asynchronous facades.
Book coordinates resolve the latest published edition unless `edition=` pins one.
Indexing a `Book` returns a `BookEntry` with book scoped exploration helpers.

```python
from bookshelf import Bookshelf

with Bookshelf() as bs:
    entry = bs.book("rcmip-emissions", "v5.1.0")["magicc-rcmip"]
    frame = entry.as_df(
        year_min=2020,
        year_max=2100,
        drop_constant=True,
        top_n=20,
        **{"region.in": "World,R5ASIA"},
    )
    facets = entry.facets()
```

`as_df()` returns pandas and uses wide indexed form for timeseries resources.
The converter family also includes `as_long_df()`, `as_scmrun()`, `as_polars()`, and `as_arrow()`.
Book timeseries queries accept server side year bounds, constant dimension removal, top N selection, row limits, and arbitrary `col.op` filters.
Lean resource and tabular queries accept `select`, `order`, `limit`, and `offset` plus the same filter vocabulary.

Use `bs.resource(tracking_id)` for an exact machine or provenance path.
`fetch()` verifies the declared SHA256 before storing bytes in the local content cache.
`as_path()` returns the verified cached file.

The asynchronous facade has the same capabilities with awaited I/O:

```python
from bookshelf import AsyncBookshelf

async with AsyncBookshelf() as bs:
    book = await bs.book("rcmip-emissions", "v5.1.0", edition=2)
    frame = await book["magicc-rcmip"].as_df()
```

## Producing and curating data

Managed resources are produced only inside an activity.
The activity derives a stable config hash, records runtime provenance, materialises the object,
and sends explicit Usage and Generation lineage to the API.
Bare strings and UUIDs in `used=` are tracking ids.
Use `Used(logical_key=...)` when key based resolution is intentional.

```python
from bookshelf import Bookshelf, Used, models

with Bookshelf() as bs:
    source = bs.book("rcmip-emissions", "v5.1.0")["magicc-rcmip"]
    with bs.activity(code_ref="github.com/example/model@abc123", config={"scenario": "ssp245"}) as activity:
        output = activity.register(
            transform(source.as_df()),
            type="timeseries",
            logical_key="model/ssp245/output",
            used=[source, Used(logical_key="model/constants")],
        )

    draft = bs.draft_book("model-results", version="v1.0.0")
    draft.attach(
        output,
        name_in_book="ssp245",
        data_dictionary=[
            models.DataDictionaryEntry(name="region", role="dimension"),
            models.DataDictionaryEntry(name="value", type="number", role="measure"),
        ],
    )
    draft.publish()
```

`register_external()` is available on both `Bookshelf` and an activity.
The former catalogues an existing pointer.
The latter attributes an external output to the current run.
Book drafting, attachment, and publication remain separate editorial calls.
Each tabular or timeseries entry can declare its own column descriptions through
``draft.attach(..., data_dictionary=...)``.
Omitting the argument preserves the entry's existing dictionary on re-attach,
while an empty list clears it.

Use `activity.register_many()` with `RegisterItem` values for a batch.
An atomic batch over 1000 items raises before any upload begins.
A larger non atomic batch is split into requests of at most 1000 items.
If any item fails, the facade finishes every chunk and raises `PartialRegistrationError`.
The error retains indexed successful outcomes, usable committed resource handles,
and each failed index with its typed `ItemError`.
Index `-1` identifies a batch level lineage failure reported by the server.
`RegisterItem.dedupe` defaults to true.
Byte identical items owned by one organisation therefore collapse to the first canonical resource,
even when later items supply a different logical key.
Returned producer handles expose `registration_status` and `registration_outcome`,
so callers can detect this `aliased` result.

A failed multipart PUT can leave an unfinished upload because the server has no abort endpoint.
Registration does not begin after that failure.
A retry reuses the content addressed upload path and safely resumes the workflow.

## Generated model core

The committed files under `src/bookshelf/_generated/` are generated from the vendored `openapi.json`.
Do not edit them by hand.
The root package and private package expose the same model module and contract provenance stamp:

```python
from bookshelf import OPENAPI_VERSION, models
from bookshelf._generated import models as private_models

assert models is private_models
```

`OPENAPI_VERSION` is copied from the vendored contract's `info.version`.
It is not the distribution version and does not assert an ordered minimum server version.

The API contract is vendored at `packages/bookshelf/openapi.json`.
Refresh that snapshot explicitly when the platform contract changes,
then regenerate and review the model diff in the same change.

The exact generation command is caller-independent and locked:

```bash
uv run --project packages/bookshelf --locked --group codegen \
  python packages/bookshelf/scripts/generate_models.py
```

The driver validates a complete temporary tree before promotion.
It retains the last-known-good tree through a same-filesystem backup and recovers a sole valid backup on startup.
Ambiguous, invalid, or multiple-backup states stop without deleting evidence.

## Credential providers (unified client)

The unified client (`bookshelf._core.client.BookshelfClient`) authenticates through
credential providers, each an `httpx.Auth` whose flow is sans-io,
so one provider object serves both the sync and async surfaces:

- `StaticToken`: a fixed bearer token, no refresh.
- `RefreshTokenExchange`: a WorkOS user access/refresh pair from `bookshelf auth login`.
  The refresh token rotates on each use and an `on_rotate` callback persists the new pair.
- `ClientCredentials`: an OAuth2 `client_credentials` machine credential.
  A refresh is a plain re-POST, there is nothing to persist.
- `BsatAssertion`: an agent identity assertion re-exchanged via the `jwt-bearer` grant
  against the API's `POST /oauth2/token`.
  It is explicit-only and never resolved from the environment.

Refresh mechanics are shared: proactive refresh five minutes before expiry,
one refresh-and-replay after an unexpected 401 (a second 401 raises `AuthenticationError`),
and single-flight refresh behind per-surface locks.
There is no background refresh task.
A token handed in with no known expiry is refreshed before first use,
because it may already be dead server-side.

When `auth=` is omitted, ambient credentials resolve in this order
(explicit beats ambient, machine beats human):

1. `$BOOKSHELF_TOKEN` as a static bearer
2. `$BOOKSHELF_CLIENT_ID` + `$BOOKSHELF_CLIENT_SECRET`, minted at `$BOOKSHELF_TOKEN_URL`
3. stored `bookshelf auth login` credentials
4. unauthenticated (public reads)

`auth=` also accepts a provider instance or a bare token string,
and an explicit `auth=None` stays unauthenticated.
`base_url` resolves as argument, then `$BOOKSHELF_API_URL`, then the production URL.

### Client lifecycle in an embedded service

The client is long-lived by design: token state lives in the provider
and each surface pools connections.
Construct one client at startup, inject it as a dependency, and close it at shutdown.
In FastAPI that is a lifespan:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from bookshelf._core.auth import ClientCredentials
from bookshelf._core.client import BookshelfClient

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.bookshelf = BookshelfClient(
        auth=ClientCredentials(client_id, client_secret, token_url=token_url),
    )
    yield
    await app.state.bookshelf.aclose()

app = FastAPI(lifespan=lifespan)

@app.get("/co2")
async def co2(request: Request):
    client: BookshelfClient = request.app.state.bookshelf
    return await client.query_resource_data_async(tracking_id)
```

Do **not** open a client per request (`async with BookshelfClient(...)` inside a handler):
that churns the connection pool and discards the cached token on every call.
Context managers are optional.
Notebooks can construct a client plainly and never close it.

## Testing

```bash
cd packages/bookshelf
uv run --locked --all-extras pytest
```

The public test suite uses local transports and fixtures.
Backend contract tests live with the private platform,
where the unpublished backend package is available.
