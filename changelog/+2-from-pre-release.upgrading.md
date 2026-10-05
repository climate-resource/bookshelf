**From a 1.0 beta or release candidate.**
The breaking changes below are listed per pull request.
The ones most likely to need action are:

- Bundles are recorded at schema 3.10, and a bundle recorded by b18 or later still loads.
- A recipe has `volume:`, `defaults:`, `build:` and `books:` sections, and every book states its own `license`.
- A recipe `uri` input over `http://` is refused, so it has to move to `https://`.
- The promised API now returns SDK-owned types instead of generated models.
  The producer and curation API is provisional, see [Outside the promise](api/index.md#outside-the-promise).
- `ResourceInfo.type` and `ResourceInfo.hash` are renamed `resource_type` and `content_hash`.
  `ResourceInfo.record` and `ResourceInfo.from_record()` are removed.
- `Book.metadata` and `Volume.metadata` are now plain dicts, with new properties alongside them.
- `BookEntry.entry` is removed. Use `name_in_book`, `visibility` and `resource_type()` instead.
- `ResourceType` members are upper case, such as `ResourceType.TIMESERIES`.
  Comparing one with a string still works.
- `correct_book()` takes keyword arguments in place of a `models.BookCorrection`.
- `item_errors` moved from `APIError` to `ConflictError`.
- A response of the wrong shape now raises the new `ContractError`.
- The `dedupe` argument is removed from `RegisterItem` and every call that registers or records a resource.
- `uuid7`, `replay_bundle`, `replay_bundle_sync` and `run_record` are no longer exported from `bookshelf`.
  Import them from `bookshelf.publisher`.
- `bookshelf.facade` is now the private `bookshelf._facade`,
  so import `Bookshelf` and the handles from `bookshelf`.
- `bookshelf.models` is no longer in `__all__`, and the generated models are private.
- The asynchronous surface is removed, so `AsyncBookshelf` and the other `Async` handles are gone.
  Call `Bookshelf` through `asyncio.to_thread` from async code.
- Agent identities are removed, along with `bookshelf auth switch` and the `--agent`, `--claim` and `--email` login flags.
  A stored agent login is ignored.
- `bookshelf.STAGING_API_URL` is removed. Pass the staging URL as `base_url` or set `$BOOKSHELF_URL`.
- `bookshelf record --book` names the version to build, in place of `--version`.
  The old flag still works but is hidden.
- A refused `record` parameter and a malformed base URL now exit 2.
- `cache prune --max-bytes` is now `--max-size-bytes`, and the old flag still works but is hidden.

The `--json` output of several commands changed, as listed in the [command line output rules](cli.md#output):

- `show`: a book lists `entries` rather than `resources`, and each entry's `bytes` is now `size_bytes`.
  An entry gains `address`.
- `record` and `validate`: `resources` is now `resource_count` and `book_entries` is now `entry_count`.
  `validate` reports `processing` as `{"code_ref": ..., "config_hash": ...}` objects rather than lists.
- `publish`: `resources` is now `resource_count`.
- `upload`: `hash` is now `content_hash`.
- `cache info`: `entries` is now `entry_count`, `total_bytes` is now `total_size_bytes`
  and `max_bytes` is now `max_size_bytes`.
- `cache prune`: `bytes_freed` is now `freed_size_bytes`,
  with `total_size_bytes` and `max_size_bytes` as for `cache info`.
- `cache clear`: `bytes_freed` is now `freed_size_bytes`.
- `search --json` ends with a `{"page": ...}` line, and `search --facets` renames `licences` to `licenses`.
- `auth list`: `expired` now means only that the access token expired,
  and `needs_login` carries the old meaning.

The `bookshelf` command line interface, its exit codes and its JSON output are outside the
[semantic versioning promise](api/index.md#outside-the-promise), so they can change in a minor release.
