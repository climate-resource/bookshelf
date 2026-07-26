# Getting started

Create a `Bookshelf` facade
and address a published book by volume and version.
Omitting `edition=` resolves the latest published edition.

```python
from bookshelf import Bookshelf

with Bookshelf() as bs:
    entry = bs.book("rcmip-emissions", "v5.1.0")["magicc-rcmip"]
    frame = entry.as_df(year_min=2020, year_max=2100)
```

Use `AsyncBookshelf` for awaited I/O:

```python
from bookshelf import AsyncBookshelf

async with AsyncBookshelf() as bs:
    book = await bs.book("rcmip-emissions", "v5.1.0", edition=2)
    frame = await book["magicc-rcmip"].as_df()
```

Publishing capabilities are part of the same SDK.
Install the `publish` extra when notebook execution is required:

```bash
uv add "bookshelf[publish]"
```

See the repository's
[package README](https://github.com/climate-resource/bookshelf/tree/main/packages/bookshelf#readme)
for complete consuming,
publishing,
authentication,
and code generation examples.
