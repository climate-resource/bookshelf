# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Reading asynchronously
#
# `AsyncBookshelf` mirrors `Bookshelf` with the same functionality,
# except that every call reaching the API is awaited.
# Everything else behaves the same way.
#
# Use this when fetching several books concurrently,
# or when the SDK is embedded in an async service.

# %% [markdown]
# ## What async buys you
#
# Skip this section if you have written async Python before.
#
# Fetching a book is mostly waiting.
# The request goes out, the server does its work, and eventually the bytes come back.
# Ordinary synchronous code spends that wait with the whole program stopped,
# so four books fetched one after another cost four waits back to back.
#
# Async code hands that waiting time back.
# `await` marks a point where a function pauses and lets other work run,
# resuming once its own answer arrives,
# and an event loop does the swapping between the functions that are paused.
#
# Two consequences follow, and both matter here.
#
# - Requests can be in flight at the same time,
#   so four fetches take roughly as long as the slowest one rather than the sum of all four.
# - Code running inside a loop must not block it,
#   because one synchronous call that stalls for a second stalls everything else on that loop too.
#
# This is concurrency rather than parallelism.
# It is still one thread doing one thing at a time, just no longer sitting idle while the network works.
# So it pays off when you are waiting on many requests,
# and does nothing at all for a single request or for heavy computation on data already in memory.
#
# Three pieces of syntax cover everything below.
#
# - `async def` declares a function that is allowed to pause.
# - `await` pauses until one result is ready.
# - `asyncio.gather(...)` starts several at once and waits for all of them.
#
# The usual first surprise is that calling an `async def` function does not run it.
# It returns a coroutine, which does nothing until it is awaited.
#
# Notebooks run inside an event loop already,
# so `await` works at the top level of a cell exactly as it does below.
# A plain `.py` script has no loop running,
# so it needs `asyncio.run(main())` as its entry point.

# %%
import asyncio
import os

os.environ.setdefault("BOOKSHELF_URL", "https://bookshelf-staging.ovh.climateresource.com.au")

from bookshelf import AsyncBookshelf

# %% [markdown]
# ## awaiting
#
# Resolving the book and converting its data are both awaited.
# Indexing the book is not, because it is a local lookup over entries already fetched.


# %%
async def latest_co2() -> tuple[str, int, tuple[int, int]]:
    async with AsyncBookshelf() as bs:
        book = await bs.book("rcmip-emissions", "v5.1.0")
        frame = await book["magicc"].as_df(
            region="World",
            variable="Emissions|CO2",
            year_min=2020,
            year_max=2100,
        )
        return book.metadata.version, book.metadata.edition, frame.shape


await latest_co2()

# %% [markdown]
# ## Fetching concurrently
#
# This is the reason to reach for the async facade in analysis work.
# One client keeps many requests in flight at once,
# so the whole set costs about as long as its slowest member.

# %%
COORDINATES = [
    ("rcmip-emissions", "v5.1.0", "magicc"),
    ("primap-hist", "v2.6", "by_region"),
    ("primap-hist", "v2.5.1", "by_region"),
]


async def shapes() -> list[tuple[str, tuple[int, int]]]:
    async with AsyncBookshelf() as bs:

        async def one(volume: str, version: str, entry: str) -> tuple[str, tuple[int, int]]:
            book = await bs.book(volume, version)
            frame = await book[entry].as_df(year_min=2000, year_max=2020)
            return f"{volume}/{version}/{entry}", frame.shape

        return await asyncio.gather(*(one(*coordinate) for coordinate in COORDINATES))


for label, shape in await shapes():
    print(f"{label:35} {shape}")

# %% [markdown]
# ## Client lifetime
#
# The client is long lived by design.
# Token state lives in the credential provider and each surface pools connections.
#
# The `async with` blocks above are fine for a script or a notebook cell.
# In a long running service they are wrong,
# because opening a client per request churns the connection pool
# and throws away the cached access token every time.
#
# Construct one client at startup and close it at shutdown.
# In FastAPI that is a lifespan.

# %% [markdown]
# ```python
# from contextlib import asynccontextmanager
#
# from fastapi import FastAPI, Request
#
# from bookshelf import AsyncBookshelf
#
#
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     app.state.bookshelf = AsyncBookshelf()
#     yield
#     await app.state.bookshelf.aclose()
#
#
# app = FastAPI(lifespan=lifespan)
#
#
# @app.get("/co2")
# async def co2(request: Request):
#     bs: AsyncBookshelf = request.app.state.bookshelf
#     book = await bs.book("rcmip-emissions", "v5.1.0")
#     frame = await book["magicc"].as_df(region="World", variable="Emissions|CO2")
#     return frame.to_dict(orient="split")
# ```

# %% [markdown]
# ## Producing asynchronously
#
# The producer surface mirrors too.
# The activity is an `async with`,
# and `register`, `draft_book`, `attach` and `publish` are all awaited.
#
# ```python
# async with AsyncBookshelf() as bs:
#     async with bs.activity(config={"scenario": "ssp245"}) as activity:
#         output = await activity.register(frame, type="timeseries")
#
#     draft = await bs.draft_book("my-volume", version="v1.0.0", license="CC-BY-4.0")
#     await draft.attach(output, name_in_book="ssp245")
#     await draft.publish()
# ```
#
# See [Publishing a book](publish_a_book) for what each of those steps means.
