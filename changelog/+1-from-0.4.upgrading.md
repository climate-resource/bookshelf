**From 0.4.**
Bookshelf 1.0 reads from the Bookshelf platform API rather than the S3 bucket,
and [Migrating from 0.4](migrating.md) walks through the upgrade.

- Python 3.12 or newer is required.
- pandas and PyArrow are core dependencies, and scmdata is no longer one.
  Install `bookshelf[scmrun]` to read `ScmRun` objects, and `bookshelf[publish]` to record notebooks.
- `$BOOKSHELF_REMOTE` is replaced by `$BOOKSHELF_URL`, which names the platform API.
- `$BOOKSHELF_CACHE_LOCATION` is replaced by `$BOOKSHELF_CACHE_DIR`.
  The old name still works but warns, and bookshelf 2.0 removes it.
- `BookShelf` and `LocalBook` still work and warn at every call.
  Bookshelf 1.1 removes them, once the feedstocks have migrated.
  An unpinned `load()` can now resolve a newer edition than 0.4 did, so pin `edition=` where it matters.
