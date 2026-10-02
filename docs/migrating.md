# Migrating from 0.4

This page is for code that reads books with bookshelf 0.4.
Bookshelf 1.0 reads from the Bookshelf platform API instead of reading straight from an S3 bucket.
The existing books and their editions were migrated to the new platform.

Publishing moved as well.
`bookshelf-producer` is retired, and feedstocks publish through the record and replay workflow
described in [Publishing a book](how-to-guides/publish_a_book.py).

## Upgrade in two steps

1. Upgrade the package and keep your code as it is.
   The 0.4 `BookShelf` and `LocalBook` still work in 1.0 and warn at every call.
2. Move each warning call site to the new API, using the [mapping](#api-mapping) below.

The first step gets you onto the platform quickly.
The second step has to be done before bookshelf 2.0, which removes the old classes.

## Step 1: upgrade

Bookshelf 1.0 needs Python 3.12 or newer.
scmdata is no longer a core dependency, so install the `scmrun` extra if you read `ScmRun` objects:

```bash
uv add "bookshelf[scmrun]>=1.0"
```

Code that imports from the top-level `bookshelf` package runs unchanged:

```python
from bookshelf import BookShelf

shelf = BookShelf()
book = shelf.load("rcmip-emissions", "v5.1.0")
run = book.timeseries("magicc")
```

Every old call emits a `DeprecationWarning` naming its replacement.
Python hides these outside `__main__` by default, so turn them on to find every call site:

```bash
python -W default::DeprecationWarning your_script.py
```

Use `-W error::DeprecationWarning` in your test suite once you have migrated,
so a stray old call fails rather than lingering.

The compatibility layer differs from 0.4 in a few places:

- `remote_bookshelf=` and `$BOOKSHELF_REMOTE` are ignored with a warning.
  Set `$BOOKSHELF_URL` to choose a deployment instead.
- `BookShelf(path=...)` becomes the content cache directory, and `$BOOKSHELF_CACHE_LOCATION` still works.
  The 0.4 cache is not reused, so the first read downloads each book again.
- `load(force=True)` is accepted and ignored, because there is no metadata cache to refresh.
- `LocalBook.metadata()` returns a dict of the old shape, but without the `profile` key
  and with a `metadata` key holding the platform's book metadata.
  Each resource carries only `name`, `timeseries_name`, `type` and `tracking_id`,
  so code reading `filename`, `hash` or `shape` from it breaks.
- `list_versions()` lists each version once, where 0.4 repeated a version for every edition.
  It also includes private versions the caller is allowed to see.
- The 0.4 submodules `bookshelf.shelf`, `bookshelf.book`, `bookshelf.errors` and `bookshelf.schema` are gone.
  Import `BookShelf` and `LocalBook` from `bookshelf`,
  and `UnknownBook`, `UnknownVersion` and `UnknownEdition` from `bookshelf.legacy`.
- `bookshelf.constants`, `bookshelf.utils` and `bookshelf.dataset_structure` are gone with no replacement.
  Helpers such as `print_dataset_structure` have to be copied into your own code.

## Step 2: move to the new API

### API mapping

Note the subtle change in capitalisation from `BookShelf` to `Bookshelf`.

| 0.4                                  | 1.0                                                      |
| ------------------------------------ | -------------------------------------------------------- |
| `BookShelf()`                        | `Bookshelf()`                                            |
| `BookShelf(path=...)`                | `Bookshelf(cache=ContentCache(path))`                    |
| `shelf.load(name, version)`          | `bs.book(name, version)`                                 |
| `shelf.load(name, version, edition)` | `bs.book(name, version, edition=edition)`                |
| `shelf.load(name)`                   | `bs.book(name, bs.volume(name).latest)`                  |
| `shelf.list_versions(name)`          | `bs.volume(name).versions`                               |
| `shelf.is_available(name, version)`  | `bs.book(...)`, catching `NotFoundError`                 |
| `shelf.is_cached(...)`               | No check-only call. `as_path()` fills the cache.         |
| `book.long_version()`                | `f"{book.version}_e{book.edition:03}"`                   |
| `book.metadata()`                    | `book.volume`, `book.version` and `book.metadata`        |
| `book.metadata()["resources"]`       | `book.entry_names`, a tuple of names without suffixes    |
| `book.timeseries(name)`              | `book[name].as_scmrun()`                                 |
| `book.get_long_format_data(name)`    | `book[name].as_long_df()`                                |
| `UnknownBook`, `UnknownVersion`      | `bookshelf.NotFoundError`                                |

`bs.volume(name).editions(version)` lists the editions of a version,
which 0.4 had no call for.

### Before and after

```python
from bookshelf import BookShelf

shelf = BookShelf()
book = shelf.load("rcmip-emissions", "v5.1.0")
print(book.long_version())

run = book.timeseries("magicc")
long = book.get_long_format_data("magicc")
```

```python
from bookshelf import Bookshelf

with Bookshelf() as bs:
    book = bs.book("rcmip-emissions", "v5.1.0", edition=1)
    print(book.version, book.edition)

    entry = book["magicc"]
    run = entry.as_scmrun()
    long = entry.as_long_df()
```

`Bookshelf` holds an HTTP connection pool.
In long-running code, use it as a context manager or call `bs.close()` so the connections close when you are done.
[Getting started](getting_started.md) covers `AsyncBookshelf`,
and [Reading a published book](how-to-guides/read_a_book.py) covers the other converters.

### Reading data

Each entry offers several shapes of the same resource:

- `as_scmrun()` returns an `scmdata.ScmRun`, like `timeseries()` did.
- `as_df()` returns a wide pandas frame, indexed by the metadata columns, with one column per year.
  The year columns are strings such as `"1750"`.
  Pass `int_years=True` to label them as integers instead.
- `as_long_df()` returns a tidy frame with integer `year` and a `value` column.
- `as_polars()`, `as_arrow()`, `preview()` and `download()` are new.

`as_long_df()` is not the 0.4 long format.
The old one named its column `values` and stored `year` as strings like `"1750-01-01 00:00:00"`.
Pass `legacy_columns=True` to get that exact format while you update downstream code.

The converters take a year window and exact match filters.
They apply to the cached download by default, and `server_side=True` has the platform select instead:

```python
entry.as_df(year_min=2000, year_max=2010, filters={"region": "World"})
```

A filter on a column the resource does not have raises `SelectionError`, a `KeyError`.
Previously you filtered the `ScmRun` or `DataFrame` yourself, which still works.

## Behaviour to check

Upgrading can change your results even where the code runs cleanly.
Check each of these against your own usage.

### Pin the edition

Omitting the edition loads the latest one, and the platform can hold newer editions than the S3 bucket did.
For example, 0.4 loads `rcmip-emissions` `v5.1.0` as edition 1, and 1.0 loads edition 2.
Pass `edition=` wherever reproducibility matters.

New versions are only published to the platform.
`primap-hist` `v2.8` exists there, for example, and 0.4 cannot see it.

### Entry names lose their suffix

0.4 stored resources in wide and long formats under names such as `by_country_wide`,
and `timeseries("by_country")` added the wide suffix for you.
In 1.0 an entry has one name, `by_country`,
and `book["by_country_wide"]` raises `EntryNotFoundError`, a `KeyError`, listing the names that exist.

A book can also carry entries that are not data, such as `build.ipynb` and `build.html`,
the notebook that built it.
Check `book[name].resource_type()` before treating every entry as a timeseries.

### Labels can differ between editions

Values are fixed per edition, but labels such as scenario names may change from one edition to the next.
Filtering on a label that no longer exists returns an empty `ScmRun` rather than an error.
Check hard-coded labels against the edition you load,
especially when an unpinned read moves you to a newer one.

### Row order is not guaranteed

Rows can come back in a different order.
Sort by the metadata columns before comparing frames or taking positional slices.

## Configuration

| 0.4                          | 1.0                                                            |
| ---------------------------- | -------------------------------------------------------------- |
| `$BOOKSHELF_REMOTE`          | `$BOOKSHELF_URL`, naming the platform API rather than a bucket |
| `$BOOKSHELF_CACHE_LOCATION`  | `$BOOKSHELF_CACHE_DIR`, with the old name as a fallback        |

[Configuration](configuration.md) lists every setting.

The cache is keyed by content hash and shared between books,
so a resource that appears in two editions downloads once.
Cached files have no file extension.
`bookshelf cache` inspects and clears it.
