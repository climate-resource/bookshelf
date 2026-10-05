**From a 1.0 beta or release candidate.**
These are the changes since the betas that can break existing code, grouped by area.

*Reading data*

- The asynchronous surface is removed, so `AsyncBookshelf` and the other `Async` handles are gone.
  Call `Bookshelf` through `asyncio.to_thread` from async code.
- The promised API returns SDK-owned types instead of generated models, and `bookshelf.models` is private.
- `Book.metadata` and `Volume.metadata` are plain dicts, with properties such as `book.version` and `volume.title` alongside them.
- `BookEntry.entry` is removed. Use `name_in_book`, `visibility` and `resource_type()` instead.
- `ResourceInfo.type` and `ResourceInfo.hash` are renamed `resource_type` and `content_hash`.
  `ResourceInfo.record` and `ResourceInfo.from_record()` are removed.
- `ResourceType` members are upper case, such as `ResourceType.TIMESERIES`.
  Comparing one with a string still works.
- The converters read the whole resource through the content cache, rather than a server-trimmed preview.
- `query()` is removed. Use a converter for complete data, or `preview()` for a bounded sample.
- Filters are passed as `filters={"region": ["World", "OECD"]}` rather than as keywords.
- `preview()` returns a `DataPreview`, and `schema()` is renamed `series_metadata()`.
- `Resource.metadata` and `Resource.type` are replaced by `describe()` and `resource_type()`.
- `as_scmrun()` raises `NonUniqueMetadataError` for rows with duplicate metadata, rather than averaging them.
- `Bookshelf.list_books()` is removed. Use `volume.versions`, `volume.latest` and `volume.editions(version)`.
- `correct_book()` takes keyword arguments in place of a `models.BookCorrection`.
- pandas and PyArrow are core dependencies and the `dataframes` extra is gone.
  Polars is no longer installed, so install it yourself for `as_polars()`.

*Errors*

- A missing entry raises `EntryNotFoundError`, and a filter on an unknown column raises `SelectionError`.
  Both are still `KeyError`s.
- `volume["missing"]` raises `VersionNotFoundError`, which is both a `KeyError` and a `NotFoundError`.
- The 400 and 422 error is renamed `RequestValidationError`.
- A response of the wrong shape raises the new `ContractError`.
  `GatewayError` now means only a non-JSON response from something in front of the API.
- `item_errors` moved from `APIError` to `ConflictError`.
- Data reads, 500 responses and connect timeouts are no longer retried.

*Configuration and authentication*

- The default API URL is the production deployment.
  Logins are stored per deployment, so run `bookshelf auth login` again.
- `bookshelf.STAGING_API_URL` is removed. Pass the staging URL as `base_url` or set `$BOOKSHELF_URL`.
- A base URL with a query string, a fragment, a `user@` part or a trailing `/v1` raises `ConfigurationError`.
- The OS keychain store is removed, so `$BOOKSHELF_USE_KEYCHAIN` does nothing.
- Agent identities are removed, along with `bookshelf auth switch` and the `--agent`, `--claim` and `--email` login flags.
  A stored agent login is ignored.

*Publishing*

- A recipe has `volume:`, `defaults:`, `build:` and `books:` sections, and every book states its own `license`.
- A recipe `uri` input must be a public `https` URL.
- Bundles are recorded at schema 3.10, and a bundle recorded by b18 or later still loads.
- `logical_key=` is renamed `name=` on `Used`, `RegisterItem` and the registration calls.
- The `dedupe` argument is removed. The server aliases matching bytes unless a bundle pins its tracking id.
- `data_dictionary=` moved from book drafting to `DraftBook.attach()`.
- `draft_book(citation_doi=...)` is removed. Pass `discovery={"doi": ...}` instead.
- `uuid7`, `replay_bundle` and `run_record` are imported from `bookshelf.publisher` rather than `bookshelf`.
  `replay_bundle` is synchronous and takes a `Bookshelf`, and `replay_bundle_sync` is removed.
- `bookshelf record` refuses a `-p` parameter the build does not assign at the top level,
  and fails a build that calls `sys.exit`.
- A `bookshelf://` reference spells its edition `_eNNN`, padded to three digits from `_e001`.

*Command line*

- `--api-url` goes before the subcommand, as in `bookshelf --api-url URL publish bundle`.
- `bookshelf record --book` names the version to build. The old `--version` still works but is hidden.
- `cache prune --max-bytes` is now `--max-size-bytes`, and the old flag still works but is hidden.
- A refused `record` parameter and a malformed base URL exit 2.
- The text output is rendered from the `--json` document, so parse `--json` rather than the text.
- Several `--json` keys changed, as listed in the [command line output rules](cli.md#output).
  `show` lists `entries` with `size_bytes`, counts end in `_count` and sizes end in `_size_bytes`.
  `search` rows and `show VOLUME` report `latest_license` and `latest_publisher`.
- `auth list` `expired` now means only that the access token expired, and `needs_login` carries the old meaning.

The command line interface, its exit codes and its JSON output are outside the
[semantic versioning promise](api/index.md#outside-the-promise), so they can change in a minor release.
