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
# The SDK is synchronous.
# From async code, run each call in a worker thread with `asyncio.to_thread`,
# so the event loop keeps serving other work while the request waits on the network.
#
# One `Bookshelf` can be shared between threads.
# Its connection pool, token refresh and download cache are built for concurrent use.
#
# Notebooks run inside an event loop already,
# so `await` works at the top level of a cell.
# A plain `.py` script needs `asyncio.run(main())` as its entry point.

# %%
import asyncio

from bookshelf import Bookshelf

bs = Bookshelf()

# %% [markdown]
# ## One call
#
# Resolving the book and reading its data are separate calls, so each goes to a thread.
# Indexing the book is a local lookup and needs no thread.

# %%
book = await asyncio.to_thread(bs.book, "rcmip-emissions", "v5.1.0")
frame = await asyncio.to_thread(
    book["magicc"].as_df,
    filters={"region": "World", "variable": "Emissions|CO2"},
    year_min=2020,
    year_max=2100,
)
book.version, book.edition, frame.shape

# %% [markdown]
# ## Fetching concurrently
#
# Wrap the synchronous steps for one book in a function,
# then gather one thread per book.
# The whole set costs about as long as its slowest member.

# %%
COORDINATES = [
    ("rcmip-emissions", "v5.1.0", "magicc"),
    ("primap-hist", "v2.6", "by_region"),
    ("primap-hist", "v2.5.1", "by_region"),
]


def shape(volume: str, version: str, entry: str) -> tuple[str, tuple[int, int]]:
    frame = bs.book(volume, version)[entry].as_df(year_min=2000, year_max=2020)
    return f"{volume}/{version}/{entry}", frame.shape


for label, size in await asyncio.gather(
    *(asyncio.to_thread(shape, *coordinate) for coordinate in COORDINATES)
):
    print(f"{label:35} {size}")

# %%
bs.close()

# %% [markdown]
# ## In a service
#
# Construct one client at startup and close it at shutdown.
# Opening a client per request churns the connection pool
# and throws away the cached access token every time.
#
# FastAPI runs a plain `def` endpoint in its thread pool,
# so the synchronous calls can be made directly there.
#
# ```python
# from contextlib import asynccontextmanager
#
# from fastapi import FastAPI, Request
#
# from bookshelf import Bookshelf
#
#
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     with Bookshelf() as bs:
#         app.state.bookshelf = bs
#         yield
#
#
# app = FastAPI(lifespan=lifespan)
#
#
# @app.get("/co2")
# def co2(request: Request):
#     bs: Bookshelf = request.app.state.bookshelf
#     book = bs.book("rcmip-emissions", "v5.1.0")
#     frame = book["magicc"].as_df(
#         filters={"region": "World", "variable": "Emissions|CO2"}, server_side=True
#     )
#     return frame.to_dict(orient="split")
# ```
