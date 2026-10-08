# Changelog

Versions follow [Semantic Versioning](https://semver.org/) (`<major>.<minor>.<patch>`)
for the Python API that [the API reference](api/index.md#what-semver-covers) lists.
Breaking changes to it only land in major versions,
with advance notice in the **Deprecations** section of releases.
The command line interface may change between minor versions,
and the bundle and recipe formats follow their own schema versions.


<!--
You should *NOT* be adding new changelog entries to this file, this
file is managed by towncrier. See changelog/README.md.

You *may* edit previous changelogs to fix problems like typo corrections or such.
To add a new changelog entry, please see
https://pip.pypa.io/en/latest/development/contributing/#news-entries,
noting that we use the `changelog` directory instead of news, md instead
of rst and use slightly different categories.
-->

<!-- towncrier release notes start -->

## bookshelf v1.1.1 (2026-10-08)

### Bug Fixes

- Pointer names may now hold `/` between segments, so pointers such as `rdm://slice/<volume>/<version>/<entry>` record and validate.
  A segment may not be empty, `.` or `..`. ([#316](https://github.com/climate-resource/bookshelf/pull/316))


## bookshelf v1.1.0 (2026-10-08)

### Features

- Added `ResourceInfo.external_uri` and `ResourceInfo.link_url`,
  so `describe()` now gives an external pointer's target and an https link to it.
  Both are `None` for resources the platform stores. ([#314](https://github.com/climate-resource/bookshelf/pull/314))

### Trivial/Internal Changes

- [#313](https://github.com/climate-resource/bookshelf/pull/313)


## bookshelf v1.0.0 (2026-10-05)

### Upgrading

- **From 0.4.**
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
- **From a 1.0 beta or release candidate.**
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

### Deprecations

- Kept the 0.4 consumer API working on top of the platform, with a `DeprecationWarning` at every call.

  - `bookshelf.BookShelf` and `bookshelf.LocalBook` still resolve,
    and live in `bookshelf.legacy` alongside the old `UnknownBook`, `UnknownVersion` and `UnknownEdition` errors.
  - `BOOKSHELF_CACHE_LOCATION` is honoured as a fallback for `BOOKSHELF_CACHE_DIR`,
    and `BOOKSHELF_REMOTE` or a `remote_bookshelf` URL now warns instead of being silently ignored.
  - `as_long_df(legacy_columns=True)` reproduces the 0.4 long format.

  ([#203](https://github.com/climate-resource/bookshelf/pull/203))
- Deprecated three spellings, which still work with a warning and will be removed in bookshelf 2.0:

  - `as_long_df(legacy_columns=True)` warns with a `DeprecationWarning`. Use the tidy `year` and `value` columns.
  - `$BOOKSHELF_API_URL` warns with a `FutureWarning`. Set `$BOOKSHELF_URL`.
  - `$BOOKSHELF_CACHE_LOCATION` warns with a `FutureWarning`. Set `$BOOKSHELF_CACHE_DIR`.

  ([#302](https://github.com/climate-resource/bookshelf/pull/302))
- Moved `bookshelf.legacy` and the root `BookShelf` and `LocalBook` outside the semver promise.
  They are removed in bookshelf 1.1, once the feedstocks have migrated. ([#310](https://github.com/climate-resource/bookshelf/pull/310))

### Features

- Replaces the legacy V1 consumer library with the public Bookshelf SDK.
  Retires the separate `bookshelf-producer` distribution,
  because its publishing capabilities now live in the SDK. ([#136](https://github.com/climate-resource/bookshelf/pull/136))
- Allows a recorded build to declare `visibility` in its recipe, alongside the collection, licence and authors.
  An omitted `visibility` resolves to the recipe's value, then to `hidden`.
  An invalid one is still rejected. ([#137](https://github.com/climate-resource/bookshelf/pull/137))
- Adds `bookshelf record`, `bookshelf validate` and `bookshelf publish`,
  so a feedstock drives the publishing surface through one entry point.

  - `record` refuses to replace an existing bundle unless `--force` is passed.
  - `validate` checks the book framing, the entries, and every managed resource against its recorded hash.
  - `publish` reports `no-op` for an already published edition, and `--dry-run` reports without publishing.
  - A structurally invalid bundle exits 7.
  - `record` needs the `publish` extra. `validate` and `publish` run on a core install.

  ([#138](https://github.com/climate-resource/bookshelf/pull/138))
- Adds the volume lifecycle and draft cleanup to the SDK and the CLI.

  - `Bookshelf.create_volume`, `update_volume` and `delete_volume`,
    with the matching `bookshelf volume` commands.
  - Creation needs `WRITE` and deletion needs `ADMIN`, so a caller can create a volume it cannot delete.
  - `Bookshelf.discard_draft` and `update_draft`, with `bookshelf discard volume@version_eNNN`.

  ([#142](https://github.com/climate-resource/bookshelf/pull/142))
- Adds `data_dictionary=` on `DraftBook.attach()`, so a producer can declare what a book's columns mean.
  The dictionary is recorded in the bundle manifest and sent on replay,
  so it survives a record and replay round trip. ([#145](https://github.com/climate-resource/bookshelf/pull/145))
- Publishes the bundle format as a specification at `docs/explanation/bundle-format.md`.
  It describes the bytes on disk rather than the Python interface,
  so an implementation in another language can be written from it. ([#164](https://github.com/climate-resource/bookshelf/pull/164))
- Adds catalogue discovery to `Bookshelf`.

  - `search_volumes()` finds volumes by free text plus the discovery filters the CLI already accepted.
  - `list_books()` returns every book in one volume, oldest first, walking the pages itself.

  ([#166](https://github.com/climate-resource/bookshelf/pull/166))
- Adds `build.use("raw")`, which resolves a resource the recipe declares for the selected version.

  - A `uri` resource is fetched through the content cache and verified against its declared `sha256`.
  - A `path` resource is read from beside the recipe, and its digest is computed as it is read.
  - `bookshelf.setup()` now returns a `Build` rather than a `bs, book` pair.
    `build.bs` and `build.book` reach the SDK underneath.

  ([#183](https://github.com/climate-resource/bookshelf/pull/183))
- Bakes the editorial metadata a recipe resolves onto each book at publish,
  so publishing a new version no longer rewrites what every earlier version says about itself.
  Removes `citation` from the volume surface, which the platform moved onto the book. ([#188](https://github.com/climate-resource/bookshelf/pull/188))
- Adds the `bookshelf://` scheme to a recipe's `resources:`, so a feedstock can build on a published book.

  - `uri: bookshelf://primap-hist/v2.7_e002/by_country` resolves to the resource the platform already holds,
    so nothing is fetched or catalogued and `used=` cites the original.
  - The entry may be left off where the book holds exactly one,
    and the edition may be left off to take the newest.
  - A `bookshelf://` resource states no `sha256`, and may leave `type` out.

  ([#194](https://github.com/climate-resource/bookshelf/pull/194))
- Added v5.1.0.0 of the HadCRUT global mean surface temperature anomaly dataset with the book name 'hadcrut'. ([#195](https://github.com/climate-resource/bookshelf/pull/195))
- Adds `book.write(...)`, which registers an output and attaches it under one name in a single call.
  `book.add(*resources)` attaches handles that were registered inside an explicit `bs.activity(...)`
  block, each under the name it registered as.
  The sugar records the same bundle as the layered form, so a build may mix the two.
  A resource written without a `type=` is catalogued as `tabular`, and a producer states `timeseries`
  where the platform's timeseries treatment is wanted.
  The implicit activity records under a fixed `process` kind, and its config is seeded from the
  parameters `bookshelf record -p` was invoked with, so the same build recorded twice is byte identical. ([#199](https://github.com/climate-resource/bookshelf/pull/199))
- Adds seven examples covering the producer behaviour the first set left unpinned.

  - `complex-processing` writes several outputs whose `used=` edges follow the processing.
  - `defaults-and-overrides` shows what a book inherits from `defaults:` and what it replaces,
    for the discovery fields and for `defaults.resources:`.
  - `figures` publishes a png beside the frame it plots, as a document entry carrying no data dictionary.
  - `mixed-visibility` pins the precedence rule: the caller, then the book's `visibility`, then `hidden`,
    with one resource narrowed inside a public book.
  - `fetch-from-web` fetches one upstream url, verified against its declared digest and served from the
    cache on later runs, so an upstream change surfaces as a digest failure rather than as a golden diff.
  - `low-level-api` is a plain script with its own command line that records a bundle through
    `RecordingBookshelf` directly, for a pipeline that publishing is only a small part of.
    The runner discovers it by its `record.py` rather than by a recipe.
  - `reissue` records one version twice with the processing changed and the data unchanged,
    and the test suite asserts that everything the seal covers is identical across the two runs.

  ([#202](https://github.com/climate-resource/bookshelf/pull/202))
- Adds `source_url` metadata to a checked-in resource, linking to the commit the file was read at.
  The bytes are re-hosted, so this is what ties them back to the repository they came from.
  The link is omitted when the file itself is uncommitted or has moved away from the commit,
  and when the repository states no origin, holds no commit, or sits on an unrecognised forge.
  A change elsewhere in the clone does not cost the link. ([#205](https://github.com/climate-resource/bookshelf/pull/205))
- Lets a resource carry its own catalogue metadata, so a book assembled from other people's data
  credits them on the thing they made rather than on the book as a whole.
  `tags`, `description`, `authors`, `doi`, `citation`, `license` and `license_url` are now declared
  under `resources:` in a recipe for a declared input, and passed to `book.write` for a produced output.

  The bundle manifest records the fields per resource, and replay sends them.

  Also pins down what `authors` and `volume.maintainers` each claim.
  `authors` credit whoever made the data, so a feedstock that reproduces somebody else's dataset
  names them rather than whoever runs the build.
  `maintainers` are whoever runs the feedstock, which is a contact rather than a credit. ([#208](https://github.com/climate-resource/bookshelf/pull/208))
- Added `bookshelf upload FILE --type TYPE`, which puts a file on the bookshelf as an input that belongs to no book
  and prints the `bookshelf://sha256/<hex>` URI a recipe declares it by.
  A dataset that is embargoed or too large for a repository is uploaded once and named by its digest,
  so a book built from it cites the original rather than a re-hosted copy.

  - A recipe resource may now name `bookshelf://sha256/<hex>` beside the book coordinate.
  - `Bookshelf.register_file` uploads and registers a file from Python, attributing it to no activity.
  - `Bookshelf.resource_by_hash` resolves a digest into the resource your organisation holds for it.

  ([#213](https://github.com/climate-resource/bookshelf/pull/213))
- Adds `bs.volume(name)`, which resolves a volume into a handle that knows its versions and editions.
  Finding the versions of a volume meant listing its books and reading the labels off each row.
  The handle asks the platform once and exposes `versions`, `latest` and `editions(version)`,
  and indexing it by version resolves the book: `volume["v2.6"]`, or `volume.book()` for the newest. ([#215](https://github.com/climate-resource/bookshelf/pull/215))
- `used=` now records an input the recipe names by `bookshelf://sha256/<hex>`.
  An uploaded input belongs to no book and the bundle records nothing for it,
  so the manifest cites it under a new `used_digests` field on the resource record. ([#220](https://github.com/climate-resource/bookshelf/pull/220))
- Adds `bookshelf preview upload`, which stores a feedstock pull request's candidate books as one preview on the platform.
  It authenticates with the GitHub Actions OIDC token, so the workflow needs the `id-token: write` permission and holds no Bookshelf credential. ([#224](https://github.com/climate-resource/bookshelf/pull/224))
- Added `type="figure"` and `data=` to `book.write`, which saves a matplotlib figure as a png and records the values it plots beside it.
  Added the `figures` extra, which installs matplotlib. ([#229](https://github.com/climate-resource/bookshelf/pull/229))
- Added `caption=` and `alt_text=` to figure writes, which land in the figure's discovery metadata.
  A public figure without an `alt_text` is now refused when it is written, before any bytes upload. ([#230](https://github.com/climate-resource/bookshelf/pull/230))
- A figure written from a matplotlib figure now also records an svg beside its png master.
  Replay uploads the svg with the figure, and the platform serves it as the figure's vector format. ([#235](https://github.com/climate-resource/bookshelf/pull/235))
- Added `Bookshelf.ensure_authenticated()` which confirm the API accepts the client's credential.
  A missing or spent stored login now starts a browser login from a local terminal,
  or a device code login from a notebook, an SSH session or a terminal with no browser.
  Without a person to log in, it raises the new `AuthenticationRequiredError`. ([#238](https://github.com/climate-resource/bookshelf/pull/238))
- Added a GitHub Actions credential step to the ambient chain.
  Setting `BOOKSHELF_AUTH=github-actions` in a job with the `id-token: write` permission
  lets the client read its organisation's books with the token GitHub mints for the job,
  so a workflow needs no stored Bookshelf secret.
  The token is read-only, and a fresh one is minted whenever the API refuses one. ([#241](https://github.com/climate-resource/bookshelf/pull/241))
- Exposed `bookshelf.uuid7()` so producers can mint tracking ids before writing data.
  Added `whole_book: true` to recipe resources so `build.use(name)` can resolve an edition's entries by name. ([#243](https://github.com/climate-resource/bookshelf/pull/243))
- Added `register(..., role="plan")` for registering a method card as the plan an activity followed.
  A plan takes no `used=` and needs a `name`, and the platform links it to every output of the activity.
  Bundles record the plan's `role`. ([#244](https://github.com/climate-resource/bookshelf/pull/244))
- Added `Bookshelf.correct_book()`,
  which correct a published book's discovery or metadata without minting an edition. ([#246](https://github.com/climate-resource/bookshelf/pull/246))
- Exposed what a publisher tool otherwise copied from the SDK's private modules.

  - Exported `bookshelf.PRODUCTION_API_URL`.
  - Added `Bookshelf.get_or_create_volume`, which returns the volume and whether this call created it,
    treating a 409 from a concurrent creator as already present.
  - Exported `APIError` and its typed subclasses, such as `NotFoundError` and `ConflictError`.

  ([#248](https://github.com/climate-resource/bookshelf/pull/248))
- Added a `cache` argument to `Bookshelf`,
  so a caller can choose the `ContentCache` without reaching into a private attribute. ([#250](https://github.com/climate-resource/bookshelf/pull/250))
- Allows a recorded build to place a resource its organisation already holds in its book, under any unused name:

  - `book.attach` takes a handle from `build.use()`, a `bookshelf://` reference or a tracking id.
  - Replay and previews send the placed resource's `tracking_id`, and a placement adds no lineage.
  - `bookshelf validate` lists every placement.

  ([#251](https://github.com/climate-resource/bookshelf/pull/251))
- `bookshelf preview upload` accepts a bundle whose book entries are pointers, and sends each one by its `external_uri` with no bytes. ([#253](https://github.com/climate-resource/bookshelf/pull/253))
- Adds `bookshelf.auth`,
  so a library calling another Climate Resource service can reuse the Bookshelf credential.

  - `default_auth()` returns an `httpx.Auth`,
    and `strict=True` raises on a spent login instead of continuing anonymously.
  - `access_token()` returns a current bearer string for clients not built on `httpx`.

  ([#257](https://github.com/climate-resource/bookshelf/pull/257))
- Carries a recorded resource's `tracking_id` through the bundle and replay,
  so the platform registers the resource under the id the producer pinned.
  Replaying a pin needs a platform that accepts `ReplayResource.tracking_id`. ([#259](https://github.com/climate-resource/bookshelf/pull/259))
- Restored `bookshelf.__version__` and exported `DataFrameSupportError` from `bookshelf`. ([#261](https://github.com/climate-resource/bookshelf/pull/261))
- `bookshelf search` and `bookshelf show VOLUME` print the volume's `keywords`.
  `bookshelf show VOLUME@VERSION` prints the book's own `license`, `doi`, `citation` and `release_url`. ([#275](https://github.com/climate-resource/bookshelf/pull/275))
- Every SDK error can now be imported from `bookshelf`.
  The newly exported errors are:

  - `RequestValidationError`
  - `AuthConfigurationError`
  - `ActionsTokenError`
  - `OAuthError`
  - `OAuthProtocolError`
  - `EntryNotFoundError`
  - `SelectionError`
  - `InvalidBundleError`
  - `InvalidRecipeError`
  - `InvalidReferenceError`

  ([#285](https://github.com/climate-resource/bookshelf/pull/285))
- Adds `server_side=True` to `as_df()`, `as_long_df()`, `as_polars()`, `as_arrow()` and `as_scmrun()`.
  The platform then selects the rows and years, so only the selection is transferred.
  It selects the same rows as the default read of the cached file, and is never capped.
  Without an `order` the rows come in the platform's order, which can differ from the file's.

  Adds `order` to `as_df()`, `as_polars()` and `as_arrow()`, naming columns to sort by with `-` for descending.
  A year column works as a key, and missing values sort first on either route.

  Adds `preview()` to every resource handle.
  It takes the same selection plus `limit`, `order`, `top_n` and `drop_constant`.
  Its `order` takes dimension columns only, and cannot be combined with `top_n`.
  It fetches one row beyond the limit, so `completeness` reports `partial` only when rows were left out.

  Adds `download(destination)`, which copies the verified file to a path the caller owns.
  `as_path()` still returns the cached file, which the cache may evict later. ([#286](https://github.com/climate-resource/bookshelf/pull/286))
- Added `int_years` to `as_df()`, which labels a timeseries' year columns as integers rather than strings. ([#288](https://github.com/climate-resource/bookshelf/pull/288))
- Adds `refresh=True` to `Bookshelf.book` and `Volume.book`.
  It skips the remembered edition and resolves the book and its entries afresh. ([#289](https://github.com/climate-resource/bookshelf/pull/289))
- Adds `dropna=True` to `as_long_df()`, which leaves out the years with no value without ever building their rows.
  This keeps a sparse resource far smaller in memory.
  The default is unchanged and still keeps a row for every year. ([#294](https://github.com/climate-resource/bookshelf/pull/294))
- A 429 is now retried for any method, honouring `Retry-After`, and raises the new `RateLimitError` once the retries run out.
  A malformed `BOOKSHELF_URL` raises the new `ConfigurationError`, and the CLI exits 2 for it. ([#295](https://github.com/climate-resource/bookshelf/pull/295))
- CLI additions for scripts:

  - `bookshelf show` accepts a `bookshelf://` reference.
  - `auth token`, `auth logout` and `cache path` take `--json`.
  - `search --json` ends with a `{"page": ...}` line carrying the total and the next offset.
  - `volume create` accepts `--license` as well as `--licence`.
  - `record --book` names the version to build. `--version` still works but is hidden, because it clashed with `bookshelf --version`.

  ([#301](https://github.com/climate-resource/bookshelf/pull/301))
- Added `ResourceType` and `Visibility` enums, plus `Identity`, `VolumeSummary`, `VolumeSearchResults`, `Facets`, `Facet`,
  `FacetValue`, `SeriesMetadata`, `Problem`, `ItemError` and `BookCorrection` value types, all importable from `bookshelf`.

  Exported `CacheSummary`, `ContractError` and `VersionNotFoundError` from `bookshelf`.
  `correct_book()`, `update_draft()` and `discard_draft()` accept a book id as a `UUID` as well as a string,
  so `book.book_id` can be passed straight in. ([#302](https://github.com/climate-resource/bookshelf/pull/302))

### Improvements

- Makes `OAuthError` a `BookshelfError`,
  so one `except BookshelfError` around a login catches every flow failure.
  The browser and device-code flows raised a bare `Exception` subclass,
  so a caller had to catch two unrelated trees to cover a single login.

  Restores the coverage signal to CI, which the SDK adoption had dropped.
  Coverage is measured over `packages/bookshelf/src`,
  and the root and package configurations now state the same source and the same gate. ([#136](https://github.com/climate-resource/bookshelf/pull/136))
- Reads git provenance through `gitpython` rather than parsing `git` output. ([#137](https://github.com/climate-resource/bookshelf/pull/137))
- Records a resource with the book's visibility instead of always recording as `hidden`.
  `visibility` in `bookshelf.yaml` now sets the tier of the book and of everything the build records.
  Passing `visibility=` on an individual registration still sets that one resource,
  and a build that declares nothing still records `hidden`. ([#144](https://github.com/climate-resource/bookshelf/pull/144))
- Generates the client's mechanical operation methods from the `build_*` and `parse_*` pairs in `_core/ops.py`.
  CI regenerates and diffs the result, so a new API operation cannot be silently left unexposed. ([#154](https://github.com/climate-resource/bookshelf/pull/154))
- Retires the seams that only ever had one adapter.
  `retry` and `cache` are gone from `Bookshelf` and `BookshelfClient`,
  and `rand` is gone from `RetryPolicy.delay`. ([#157](https://github.com/climate-resource/bookshelf/pull/157))
- Moves the rules that decide whether a bundle is a replayable published book onto `Bundle` itself.
  `Bundle.validate` asserts them and raises the new `InvalidBundleError`,
  and `Bundle.read_validated` reads and asserts in one call.
  `bookshelf validate` keeps its output and its exit codes. ([#159](https://github.com/climate-resource/bookshelf/pull/159))
- Publishes a recorded bundle behind `bookshelf.publisher.publish_bundle`,
  which drafts once and returns a `PublishOutcome`
  carrying the kind, the edition, the resource count and the bundle hash.
  `bookshelf publish` produces the same output, and the same exit codes, as before. ([#161](https://github.com/climate-resource/bookshelf/pull/161))
- Slims the `publish` extra to `nbformat` and `nbconvert`, the two libraries notebook capture imports.
  Drops `papermill`, which brought the whole `aiohttp` stack,
  along with the `jupyter-client` and `ipykernel` pins it needed.
  `bookshelf record` no longer refuses to run when `papermill` is absent. ([#162](https://github.com/climate-resource/bookshelf/pull/162))
- Splits `bookshelf.publisher.record` into the driver, the recording adapter and the recipe,
  which now live in `bookshelf.publisher.record`, `bookshelf.publisher.recording`
  and `bookshelf.publisher.recipe`.
  The public interface is unchanged, and every name exported from `bookshelf.publisher` behaves the same. ([#164](https://github.com/climate-resource/bookshelf/pull/164))
- Records the pyarrow writer version in the bundle manifest header, under a new optional `writer` block.
  Parquet output is not stable across pyarrow versions,
  so a change in the recorded content hashes now explains itself. ([#178](https://github.com/climate-resource/bookshelf/pull/178))
- Collapses the four hand-rolled copies of the token exchange onto the credential providers.
  `bookshelf auth token` now refreshes a stored login that carries a refresh token but no recorded expiry,
  where it used to print it as it stood. ([#193](https://github.com/climate-resource/bookshelf/pull/193))
- Sends the processing fingerprint when drafting a book.
  `draft_book` now takes the `[code_ref, config_hash]` pairs of the runs that generated a book's
  members, and a recorded book states the fingerprint of the activity that produced it, so
  `bookshelf validate` reports it.
  Processing is provenance and never enters the seal, so a rebuild whose code changed but whose data
  did not converges on the existing edition. ([#199](https://github.com/climate-resource/bookshelf/pull/199))
- The local cache now remembers each resource's hash and every pinned book edition,
  so a warm `as_path()` or `fetch()` on `book(volume, version, edition=n)` makes no request at all.
  A remembered edition is rechecked with one request once a day, tuned by `BOOKSHELF_CACHE_BOOK_TTL`. ([#214](https://github.com/climate-resource/bookshelf/pull/214))
- Printing a volume, a book, a book entry, a resource or a draft book now describes what is inside it.
  The repr is a header line over named sections, the shape xarray and scmdata already use:
  the entries and their types, then the reader and explorer calls the type actually supports.
  A section with nothing in it is left out, so a document entry does not advertise `as_scmrun()`. ([#215](https://github.com/climate-resource/bookshelf/pull/215))
- Moved staging login to the dedicated Bookshelf WorkOS application. ([#231](https://github.com/climate-resource/bookshelf/pull/231))
- Bundled the production WorkOS client id and pointed `PRODUCTION_API_URL` at `https://bookshelf.climateresource.com.au`. ([#232](https://github.com/climate-resource/bookshelf/pull/232))
- Moved `gitpython` into the `publish` extra, because only the produce path reads a git repository.
  Consumers no longer install it.
  Turned the `test` extra into a dependency group, so it no longer ships in the published wheel metadata. ([#239](https://github.com/climate-resource/bookshelf/pull/239))
- Downloads each resource once when several processes or threads share a content cache.
  Concurrent fetches of one file wait on a lock under `<cache>/.locks/` instead of downloading it again.
  `ContentCache.fetch` exposes this for callers that fill the cache themselves. ([#255](https://github.com/climate-resource/bookshelf/pull/255))
- Locks the credentials file for every change,
  so processes refreshing tokens at the same time no longer lose each other's writes.

  `bookshelf auth whoami` reports client credentials as kind `machine` instead of `user`. ([#256](https://github.com/climate-resource/bookshelf/pull/256))
- Selects an external pointer on the platform rather than transferring all of it and selecting locally. ([#286](https://github.com/climate-resource/bookshelf/pull/286))
- Cached parquet reads such as `as_df()` now skip the year columns outside `year_min` and `year_max`
  and filter rows on text and missing-value filters while the file is read, before the rows reach pandas.
  Filtered reads of large resources use a fraction of the memory they did.
  A cached `tabular` read now numbers its rows from 0 after filtering or ordering, as a `server_side` read already did. ([#288](https://github.com/climate-resource/bookshelf/pull/288))
- Lowers the default `book_ttl` from one day to one hour, so a remembered pinned edition is checked again sooner. ([#289](https://github.com/climate-resource/bookshelf/pull/289))
- Rendered help, usage errors and tracebacks as plain text, so CLI output no longer changes under a TTY or `FORCE_COLOR`.

  Improved the CLI output in several places:

  - Added `bookshelf --version`.
  - `search` says when more results exist and how to page, and points at `--facets` when filters match nothing.
  - `search --type` lists the valid resource types, and `--license` is accepted alongside `--licence`.
  - `search --facets` refuses a query or filters, which the facets endpoint would ignore.
  - `auth list` marks a credential that cannot be renewed without logging in again.
  - `auth whoami --offline` reports permissions as null, because they are unknown without the API.
  - `show` separates its per-edition and per-resource blocks with a blank line.
  - Byte counts use binary units, so the 5 GiB cache cap reads `5.0 GiB`, and timestamps are given to the second.

  ([#291](https://github.com/climate-resource/bookshelf/pull/291))
- Tidied the messages `bookshelf validate` prints.
  A schema error names each field without pydantic's documentation links.
  A bundle from a newer schema major names the upgrade as its remedy rather than re-recording.
  The summary reports an absolute `bundle_path`, as `record` does. ([#292](https://github.com/climate-resource/bookshelf/pull/292))
- Lowers the peak memory of a filtered cached read, most of all when the filter keeps most of the rows. ([#294](https://github.com/climate-resource/bookshelf/pull/294))
- Cached reads of wide timeseries such as `as_df()` now keep the text label columns dictionary encoded and build the index from the dictionary codes.
  The frame is unchanged, but large resources load in about half the memory and time under pandas 2. ([#296](https://github.com/climate-resource/bookshelf/pull/296))
- A read timeout is no longer retried, so a server that stops answering fails after one 30 second timeout instead of about 93 seconds, and the error names the timeout. ([#297](https://github.com/climate-resource/bookshelf/pull/297))
- `as_long_df(dropna=True)` now shares the label values between years with the same gaps, so it never costs more memory than `dropna=False`.
  On a dense resource under pandas 3 this cuts the peak memory by about a factor of six.
  Cached wide timeseries reads are also faster under pandas 3, and now beat the reads before #296 on both pandas 2 and 3. ([#298](https://github.com/climate-resource/bookshelf/pull/298))
- CLI exit codes are documented on the new command line page and listed under `bookshelf --help`:

  - A conflict exits 8 and a response outside the API contract exits 9, where both exited 1.
  - Incomplete credential settings, a bad selection and a build outside a git repository exit 2, where they exited 1.
  - `AuthenticationRequiredError` exits 3, where it exited 1.
  - A bundle directory that does not exist exits 2, where it exited 7.

  ([#301](https://github.com/climate-resource/bookshelf/pull/301))
- A resource type, visibility or other enumerated value that a newer platform adds no longer fails to parse.
  It arrives as a member of its own, so a resource of a new type stays readable with `fetch()`, `download()` and `as_path()`. ([#302](https://github.com/climate-resource/bookshelf/pull/302))

### Bug Fixes

- Fixes a batch of defects found in review of the SDK adoption:

  - `as_long_df` no longer raises `KeyError` on a wide frame that carries year columns and no dimensions.
  - Selects the staging WorkOS client from a host label rather than any occurrence of the word in the API URL.
  - The browser login no longer fails when an incidental request reaches the loopback callback
    before the redirect.
  - An unparseable server timestamp now surfaces as a validation error rather than a bare `ValueError`.
  - Pairs batch registration outcomes with their request items by the server-reported index.
  - Raises a typed error when a registration response commits nothing, instead of `IndexError`.
  - Repairs naive timestamps when listing resources, so both resource endpoints agree.
  - A browser login no longer fails because a recent one still holds a port in `TIME_WAIT`.
  - Rejects a malformed cache digest instead of storing a file the cache can never see again.

  ([#136](https://github.com/climate-resource/bookshelf/pull/136))
- Reports why record mode cannot start, rather than reporting one ambiguous cause.
  A failure to derive the code reference now names the unmet requirement,
  and `setup` outside a recording says no recording is active rather than blaming a missing argument.
  An invalid `visibility` in the recipe is reported as a Bookshelf error rather than a `TypeError`. ([#137](https://github.com/climate-resource/bookshelf/pull/137))
- Fixes publishing a second version of a feedstock whose source data has not changed.
  Recording wrote each generated resource's inputs back over the resources already recorded,
  so the first output listed itself as its own input and replay then failed to resolve it.
  Bundles recorded before this still replay. ([#143](https://github.com/climate-resource/bookshelf/pull/143))
- Normalises the git remote URL before recording it as a book's `code_ref`, so only the addressing part is stored.
  Producers running from CI should check whether their `origin` is configured in a form that embeds a token, and rotate it if so. ([#149](https://github.com/climate-resource/bookshelf/pull/149))
- Writes the credential store atomically. ([#150](https://github.com/climate-resource/bookshelf/pull/150))
- Confines the SDK retry policy to requests that are safe to replay,
  so a transient 5xx can no longer duplicate a write.

  - Only idempotent methods are retried on a 5xx. A `POST` or a `PATCH` now surfaces the error to the caller.
  - A network failure on a write is only retried when the connection never came up.
  - `501` and `505` are no longer retried on any method.

  ([#156](https://github.com/climate-resource/bookshelf/pull/156))
- Raises a typed `DataFrameSupportError` with an install hint from `as_polars()` when Polars is missing,
  instead of a bare `ImportError`. ([#157](https://github.com/climate-resource/bookshelf/pull/157))
- Bumps pint to 0.25.3 and flexparser to 0.4 in the lockfile.
  The old pair failed to import under Python 3.13 with a frozen dataclass `TypeError`,
  which broke the scmrun extra outright. ([#182](https://github.com/climate-resource/bookshelf/pull/182))
- Adopts the `release_url` and `citation` discovery fields from the live contract.
  The server started returning them and `DiscoveryProfile` forbids unknown fields,
  so listing volumes failed validation and broke the docs build. ([#184](https://github.com/climate-resource/bookshelf/pull/184))
- Falls back to anonymous access when a stored login cannot be refreshed, instead of failing the call.
  A spent credential used to deny the caller the public books that need no credential at all.
  The warning that replaces the failure names the fix: `bookshelf auth logout` to discard the stored credential, or `bookshelf auth login` to claim a fresh one. ([#187](https://github.com/climate-resource/bookshelf/pull/187))
- Fixed reading a stored wide timeseries file, whose date-stamped year columns were taken for dimensions. ([#203](https://github.com/climate-resource/bookshelf/pull/203))
- Fixed published-book iteration to yield entry names in platform order,
  so `list(book)` lists them in order. ([#204](https://github.com/climate-resource/bookshelf/pull/204))
- Records a checked-in `path:` resource as managed bytes rather than as a pointer at its repository
  path. The platform only accepts an `https` pointer it can fetch again, so a bundle carrying a
  checked-in input could be recorded and validated but never published. ([#205](https://github.com/climate-resource/bookshelf/pull/205))
- Stopped a pre-release bump from consuming the changelog fragments.
  They describe the release the pre-releases are leading up to, so building the changelog under a
  `b` or `rc` version files them against a version nobody reads the notes of. ([#206](https://github.com/climate-resource/bookshelf/pull/206))
- A live registration that stated no authors was refused by the platform with a validation error.
  An unstated discovery fact is now left off the wire rather than sent as null. ([#213](https://github.com/climate-resource/bookshelf/pull/213))
- Replaying a bundle sent every discovery fact the manifest omitted as an explicit null,
  which the platform refused with a validation error naming each resource.
  An unstated fact is now left off the replay request, matching what the live path already did. ([#217](https://github.com/climate-resource/bookshelf/pull/217))
- Serialises string, binary, list, struct and categorical columns from a pandas frame
  to the same parquet bytes as the equivalent polars frame,
  so a record hashes the same whichever library built it.

  - Casts those columns to large offsets and categorical indices to `uint32`,
    the widths polars already writes.
  - Drops library metadata from every column, such as the category labels polars attaches.
  - Changes the hash of a resource built from pandas on pandas 2.x,
    from a pandas frame holding binary, list, struct or categorical columns,
    or from a polars frame holding categorical or enum columns.
    Re-recording such a book publishes new bytes rather than converging.
  - Reads a polars `Enum` column back from the parquet file as `Categorical`.

  ([#222](https://github.com/climate-resource/bookshelf/pull/222))
- Preview uploads now carry the build's activity and each resource's lineage, metadata and discovery,
  so a book published from a pull request keeps its provenance.
  A checked-in input recorded with `register_file` travels under the preview too,
  registered with its lineage but attached to no book. ([#234](https://github.com/climate-resource/bookshelf/pull/234))
- Fixed `as_scmrun()` dropping timeseries whose values were all missing. ([#236](https://github.com/climate-resource/bookshelf/pull/236))
- Caps `httpx` below 1.0.
  The `1.0.dev` prereleases remove `httpx.Auth`, so `bookshelf` failed on import when prereleases were allowed. ([#237](https://github.com/climate-resource/bookshelf/pull/237))
- Re-verified a cached `uri` input before a recorded build uses it,
  and raised `HashMismatchError` when a download does not match its declared digest.

  Kept a resource larger than the cache cap readable after it is downloaded,
  where the eviction used to remove it before the caller could read it. ([#250](https://github.com/climate-resource/bookshelf/pull/250))
- Skips writing a refreshed token back to a stored login when that login changed since it was loaded,
  so a refresh cannot overwrite a newer login or bring back one that was logged out. ([#256](https://github.com/climate-resource/bookshelf/pull/256))
- Fixed `bookshelf show --help`, which crashed because its argument help was read as markup. ([#261](https://github.com/climate-resource/bookshelf/pull/261))
- Applied a recipe's `volume:` section to the volume on publish.
  Recording used to drop `maintainers`, `keywords`, `update_cadence` and the deprecation fields silently.
  Sent only the fields the recipe states, so a volume fact it leaves out keeps its value. ([#277](https://github.com/climate-resource/bookshelf/pull/277))
- Refreshes a pinned edition's book metadata and visibility when the edition is checked again after `book_ttl`.
  A correction made with `correct_book` previously never reached a cached edition. ([#289](https://github.com/climate-resource/bookshelf/pull/289))
- Fixed `bookshelf show` reporting the resource id as `tracking_id` and leaving `content_hash` null.

  Refused malformed CLI addresses with exit 2 before they reach the API.
  Dot segments, a second `@`, and malformed or non-ASCII editions used to parse and then fail with exit 5,
  and `show .` printed a traceback.

  Reported an unusable cache directory as a usage error naming `BOOKSHELF_CACHE_DIR` instead of a traceback.

  Named the `$BOOKSHELF_TOKEN` remedy when the server rejects the env token, rather than `bookshelf auth login`. ([#291](https://github.com/climate-resource/bookshelf/pull/291))
- Fixed `bookshelf validate` passing bundles edited by hand after recording.
  It now refuses:

  - a resource name recorded twice, or a book entry that appears twice
  - a managed resource whose recorded `size` differs from its bytes
  - a book `visibility` other than `hidden`, `org` or `public`
  - a volume or version the platform cannot address, such as one over 100 or 50 characters, or `../../etc`
  - `processing` that does not match the activity
  - an activity whose `config_hash` is not the digest of its parameters and whose `activity_id` is not derived from them
  - a pointer the platform would refuse, such as `file:///etc/passwd`, or one whose bytes still sit in the bundle
  - a byte file that is a symlink resolving outside the bundle, which replay also refuses now

  Validate also hashes resources in chunks, so its memory no longer grows with the largest file.

  ([#292](https://github.com/climate-resource/bookshelf/pull/292))
- Made `bookshelf record` refuse unsafe input before running the build, and record a clean code ref.

  - `--force` no longer replaces a file, a non-empty directory without `manifest.lock`, or a directory holding the recipe, build file or working directory.
  - A `-p` value that is malformed YAML, a date, binary, NaN or infinity now exits 2 before the build runs, rather than crashing after it or recording NaN as `null`.
  - `code_ref` is read before the bundle is staged and before the build runs, so a clean clone no longer records `+dirty`, and a build that changes directory still records its clone.
  - A build that calls `sys.exit` now fails the record with a message, rather than exiting with no bundle.
  - An unreadable recipe, a key stated twice in a recipe and an invalid resource name now raise a `BookshelfError` naming the problem.
  - A lone surrogate printed by a build no longer crashes the notebook render.
  - Clearer messages for a numeric version in the recipe, a book coordinate input passed to `used=`, a resource named like the executed notebook, and a build that writes no outputs.

  ([#293](https://github.com/climate-resource/bookshelf/pull/293))
- Accepts numpy arrays, pandas indexes and series, sets and numpy scalars as filter values and year bounds.
  Previously `filters={"region": df.index.unique("region")}` raised `TypeError`.

  Refuses a malformed read before any request is made:

  - `book()` with a version that is not a non-empty string, or an edition below 1.
  - `preview()` with a `limit` or `top_n` that is not a positive whole number.
  - `resource_by_hash()` with anything but a `sha256:` digest, which now raises `ValueError` rather than `NotFoundError`.

  Names `int_years` when `as_df(int_years=True)` is refused on a tabular resource.

  An unknown filter column on a `server_side=True` read now lists the columns, as a cached read does.

  ([#294](https://github.com/climate-resource/bookshelf/pull/294))
- Fixed several transport failures.

  - An HTML error page no longer appears in an error message, which now names the status and the URL instead.
  - `bs.volume(".")` and `bookshelf show .` no longer reach the volume list endpoint.
  - Network failures and timeouts now name the URL they failed on.
  - `RequestValidationError` messages now list the field errors.
  - Removing the cache directory during a session no longer breaks later reads, and a cache path blocked by a file raises the new `CacheDirectoryError`.
  - Waiting for the stored credentials lock now times out after 30 seconds instead of hanging.

  ([#295](https://github.com/climate-resource/bookshelf/pull/295))
- A success response that is not the JSON the operation returns, such as the web app's page answering a base URL with the wrong path, now raises `GatewayError` (CLI exit 6) naming the status, content type and URL, instead of a raw `JSONDecodeError`, `ValidationError` or `AttributeError`.
  A rate limited download from the content CDN is now retried, honouring `Retry-After`, and a 429 message now says it was rate limited and gives the status.
  A failed token refresh no longer quotes an HTML body, and the CLI prints a warning as one `Warning:` line rather than a Python warning with source lines.
  `bookshelf auth whoami` now says whether a rejected token expired, is malformed, or is revoked or issued for another deployment. ([#297](https://github.com/climate-resource/bookshelf/pull/297))
- Fixed several edge cases in consuming resources.

  - A NaN, `pd.NA` or `pd.NaT` filter value now selects the missing rows, as `None` does, on both the cached and the server side route. Listed with other values it raises the same `ValueError` as `None` instead of silently dropping the missing rows.
  - A read no longer fails when another process clears the cached file under it. The file is downloaded again once.
  - A read-only cache directory now raises `CacheDirectoryError` instead of a raw `PermissionError` when it misses, and still serves the files it holds.
  - `resource_by_hash()` now accepts upper case hex instead of reporting the resource as missing.
  - `as_arrow()` no longer adds an `__index_level_0__` column to tabular resources.

  ([#298](https://github.com/climate-resource/bookshelf/pull/298))
- Fixed the packaging for 1.0.

  - The wheel and the sdist now carry the MIT licence, and the sdist no longer ships the tests.
  - Raised the floors that did not work: `typer>=0.26`, `nbconvert>=7.3`, `nbformat>=5.1` and `pyyaml>=6.0.2`.
  - A notebook render that fails on import now names the underlying `ImportError`.
  - Importing a removed 0.4 submodule such as `bookshelf.shelf` now raises an `ImportError` that links the migration guide.

  ([#300](https://github.com/climate-resource/bookshelf/pull/300))
- Fixes for the credentials file, versions and recorded activities:

  - A credentials file written by a newer `bookshelf` is read and never overwritten, where it was renamed to `credentials.json.unreadable` and the newer install was logged out. Logging in or out against it fails with exit code 2.
  - A book version ending in `_e` and digits, which cannot be addressed, is refused in recipes and bundles.
  - An activity's `runner` is `local` outside CI rather than the machine's hostname, and `CI=false` no longer counts as CI.

  ([#301](https://github.com/climate-resource/bookshelf/pull/301))
- Fixes found by the 1.0.0rc2 smoke test:

  - `series_metadata()` on an entry that is not a timeseries raises `UnsupportedConversionError`,
    without asking the platform.
  - An error status the API contract does not declare, such as a proxy's JSON 403,
    exits by its status class rather than 9.
  - `bookshelf auth login` exits 2 before contacting anything
    when the credentials file belongs to a newer bookshelf,
    or when no WorkOS client ID is known for the deployment.
  - Against a newer credentials file, errors suggest upgrading or setting `BOOKSHELF_TOKEN`
    rather than logging in or out, and `auth list` marks an expired token as `needs_login`.
  - A credentials file whose `version` is a string such as `"3"` is treated as newer rather than set aside.
  - A recipe refused for its content no longer suggests pointing `--recipe` at a different file.
  - The `figures` extra installs seaborn, which `ScmRun.lineplot()` needs.

  ([#304](https://github.com/climate-resource/bookshelf/pull/304))
- Fixed `preview()` failing validation on a resource with a `geometry` column. ([#310](https://github.com/climate-resource/bookshelf/pull/310))

### Improved Documentation

- Adds executed how-to guides covering both sides of the SDK:
  reading a book, converting and plotting, reading asynchronously,
  publishing a book, and cataloguing external data.
  Each guide runs when the docs are built, so its output is real.
  Also corrects the entry name in the existing examples, which was `magicc-rcmip` and is `magicc`. ([#166](https://github.com/climate-resource/bookshelf/pull/166))
- Adds `examples/`, one directory per example, each a miniature feedstock with its own recipe, build
  file and golden manifest.
  `examples/run_all.py` records every example, validates it and compares it against its golden, and it
  exits non-zero when any of them fails.
  The examples are both the reference that `copier-bookshelf-dataset` scaffolds from and the
  regression fixtures that catch an accidental change to the bundle format. ([#199](https://github.com/climate-resource/bookshelf/pull/199))
- Limits the API reference to the stable reading surface of the SDK.
  Only what it documents is covered by Semantic Versioning.
  The producer methods, `bookshelf.publisher`, `bookshelf.models` and the CLI can still change in any release. ([#223](https://github.com/climate-resource/bookshelf/pull/223))
- Adds a standalone Authentication page covering every way to authenticate.
  It also documents the credential precedence chain and where credentials are stored.
  `Configuration` now covers configuration alone and links across. ([#238](https://github.com/climate-resource/bookshelf/pull/238))
- Added a migration guide for code that reads books with bookshelf 0.4,
  and fixed stale claims across the authentication, development, recipe and bundle pages. ([#261](https://github.com/climate-resource/bookshelf/pull/261))
- Clarified that a null `volume:` field never clears a volume fact.
  An explicit empty list such as `keywords: []` does clear that list. ([#278](https://github.com/climate-resource/bookshelf/pull/278))
- Adds a command line page (output rules, exit codes, a generated command reference) and an addressing page for `volume@version_eNNN/entry` and `bookshelf://` references. The configuration page now lists the CI and SSH variables the SDK reads, and the authentication page says the credentials file format is private. ([#301](https://github.com/climate-resource/bookshelf/pull/301))
- The API reference no longer shows handle constructors, and says handles come from a client.
  `PartialRegistrationError` and the publisher errors are promised as classes,
  while an attribute returning a generated model is provisional.
  The credentials page describes where the file lives when `XDG_CONFIG_HOME` is set. ([#304](https://github.com/climate-resource/bookshelf/pull/304))
- Added an API reference page for `bookshelf.auth`.
  The promise now covers `default_auth`, `access_token`, `StaticToken` and `ClientCredentials`, and the other provider classes may change in any release. ([#310](https://github.com/climate-resource/bookshelf/pull/310))

### Trivial/Internal Changes

- [#160](https://github.com/climate-resource/bookshelf/pull/160), [#178](https://github.com/climate-resource/bookshelf/pull/178), [#196](https://github.com/climate-resource/bookshelf/pull/196), [#197](https://github.com/climate-resource/bookshelf/pull/197), [#213](https://github.com/climate-resource/bookshelf/pull/213), [#239](https://github.com/climate-resource/bookshelf/pull/239), [#287](https://github.com/climate-resource/bookshelf/pull/287), [#303](https://github.com/climate-resource/bookshelf/pull/303), [#311](https://github.com/climate-resource/bookshelf/pull/311)


## bookshelf v0.4.3 (2026-07-26)

### Deprecations

- `bookshelf-producer` is frozen and will be retired
  once every feedstock has migrated to support an API driven approach.
  No new features will be added to it.

  Its `bookshelf` dependency is now pinned below `0.5.0`.
  `bookshelf-producer` functionality will be integrated into the `bookshelf` package in `0.5.0`,
  and the producer write path it calls is being replaced rather than shimmed,
  so producer must stop resolving forward into it. ([#135](https://github.com/climate-resource/bookshelf/pull/135))


## bookshelf v0.4.2 (2026-05-08)

### Trivial/Internal Changes

- [#129](https://github.com/climate-resource/bookshelf/pull/129)


## bookshelf v0.4.1 (2026-05-08)

### Trivial/Internal Changes

- [#117](https://github.com/climate-resource/bookshelf/pull/117), [#126](https://github.com/climate-resource/bookshelf/pull/126)


## bookshelf v0.4 (2024-10-17)

### Breaking Changes

- The `bookshelf` package has been split into two:
  * `bookshelf` - the core package for consuming content from the bookshelf
  * `bookshelf-producer` - the CLI tool for creating and managing books

  This should require no changes for data consumers.
  This change makes for a cleaner separation between consuming
  and producing datasets.

  ([#65](https://github.com/climate-resource/bookshelf/issues/65))

### Features

- Added Climate Resource's NDCs dataset to the bookshelf ([#56](https://github.com/climate-resource/bookshelf/issues/56))
- Add a functions to add long format data and compressed files ([#58](https://github.com/climate-resource/bookshelf/issues/58))
- Add a functions to get long format data from the book ([#59](https://github.com/climate-resource/bookshelf/issues/59))
- Added 20240318 version of CAT dataset to the bookshelf ([#64](https://github.com/climate-resource/bookshelf/issues/64))
- Deploy documentation automatically via the CI ([#109](https://github.com/climate-resource/bookshelf/pull/109))

### Improvements

- When running a notebook, the files were verified through data content hash code rather than file name hash code ([#60](https://github.com/climate-resource/bookshelf/issues/60))
- Migrate to github ([#106](https://github.com/climate-resource/bookshelf/pull/106))
- Removed the primap-hist dataset from the repository.

  This dataset has been migrated to be a standalone dataset at
  [climate-resource/bookshelf-primap-hist](https://github.com/climate-resource/bookshelf-primap-hist). ([#111](https://github.com/climate-resource/bookshelf/pull/111))
- Moved the `bookshelf` package to the `packages/` directory to improve the DX when working with the repository.
  This has no user-facing impact. ([#112](https://github.com/climate-resource/bookshelf/pull/112))
- Replaced deprecated dependency `appdirs` with `platformdirs` ([#108](https://github.com/climate-resource/bookshelf/pull/108))
- Pin bookshelf version for producer ([#110](https://github.com/climate-resource/bookshelf/pull/110))


### Bug Fixes

- resolve the issue where the upload and download files have rows in a different order. ([#63](https://github.com/climate-resource/bookshelf/issues/63))

### Improved Documentation

- Updated the volume creation documentation ([#114](https://github.com/climate-resource/bookshelf/pull/114))
- Add example notebooks to docs ([#61](https://github.com/climate-resource/bookshelf/issues/61))
- Migrated documentation to use [mkdocs](https://www.mkdocs.org/).
  This allows us to write documentation in only MarkDown,
  instead of mixing reStructuredText and Markdown. ([#66](https://github.com/climate-resource/bookshelf/issues/66))

### Trivial/Internal Changes

- [#107](https://github.com/climate-resource/bookshelf/pull/107)
- [#113](https://github.com/climate-resource/bookshelf/pull/113)
- [#65](https://github.com/climate-resource/bookshelf/pull/65)


## bookshelf v0.3.0 (2024-01-31)


### Features

- * Added legacy GDP results from Excel NDC Tool. ([#42](https://github.com/climate-resource/bookshelf/issues/42))
- Add an updated version of the World Bank's World Development Indicators (v23). The `wdi` book has also been
  updated to edition 2. ([#43](https://github.com/climate-resource/bookshelf/issues/43))
- * Added greenhouse gas emissions data from Climate Action Tracker (CAT).
  * Added historical greenhouse gas emission data and projection data from PBL Netherlands Environmental Assessment Agency.
  * Added estimated energy sector CO2 emissions data from International Energy Agency.

  ([#45](https://github.com/climate-resource/bookshelf/issues/45))
- Add a function to display the structure of a dataset ([#48](https://github.com/climate-resource/bookshelf/issues/48))
- Add data dictionary to schema ([#49](https://github.com/climate-resource/bookshelf/issues/49))
- Add data dictionary verification ([#50](https://github.com/climate-resource/bookshelf/issues/50))
- Added NGFS3 emissions data. ([#53](https://github.com/climate-resource/bookshelf/issues/53))

### Bug Fixes

- Fix to the schema for datasets to allow no files to be specified ([#47](https://github.com/climate-resource/bookshelf/issues/47))
- Re-add notebook tests to CI

  Updated primap-hist and primap-ssp-downscaled editions to update reflect the renaming of `turkey` to `Türkiye` ([#51](https://github.com/climate-resource/bookshelf/issues/51))

### Trivial/Internal Changes

- [#55](https://github.com/climate-resource/bookshelf/issues/55)


## bookshelf v0.2.4 (2023-08-14)


### Features

- Added the Biennial Reports Common Table Format data reported by Annex-I parties as un-br-ctf.

  For now, contains the GHG projections data. ([#38](https://github.com/climate-resource/bookshelf/issues/38))

### Bug Fixes

- Add CLI entrypoint that was inadvertently missed when migrating to the new copier template. ([#39](https://github.com/climate-resource/bookshelf/issues/39))
- Fixed the un-br-ctf dataset, now includes a lot more data.

  Version 2023-08, edition 1 of the un-br-ctf dataset is to be considered broken, always
  use edition 2 instead. ([#40](https://github.com/climate-resource/bookshelf/issues/40))

### Improved Documentation

- Added documentation about generating and using new versions of Books locally. ([#41](https://github.com/climate-resource/bookshelf/issues/41))


## bookshelf v0.2.3 (2023-07-28)


### Features

- Add PRIMAP downscaled SSPs dataset: `primap-ssp-downscaled` ([#34](https://github.com/climate-resource/bookshelf/issues/34))
- Migrate to the common Climate Resource copier template

  Major changes include adding support for the use of `towncrier` for managing the changelogs and `liccheck` for verifying
  the compliance of any project dependencies. ([#35](https://github.com/climate-resource/bookshelf/issues/35))

### Improvements

- Use original region abbreviations in PRIMAP-hist. Bumps `primap-hist` to edition 4. ([#34](https://github.com/climate-resource/bookshelf/issues/34))
- Extract SSP marker scenarios in addition to the existing baseline scenarios. Bumps `primap-ssp-downscaled` to ed.2 ([#36](https://github.com/climate-resource/bookshelf/issues/36))

### Bug Fixes

- Convert PRIMAP-hist to units of the form `kt X / yr` to be consistent. Bumps `primap-hist` to ed.3 ([#32](https://github.com/climate-resource/bookshelf/issues/32))


## v0.2.2

### Added

- ([!27](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/27)) Add sphinx-based documentation
- ([!26](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/26)) Add `force` option to the publish CLI command to upload data even if a matching edition already exists
- ([!25](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/25)) Add primap-hist v2.4.1 and v2.4.2

### Changed

- ([!29](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/29)) Move `python-dotenv` from a development dependency to a core dependency
- ([!23](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/23)) Fix CEDs unit names for all resources. Bumps `ceds` to ed.3

### Fixed

- ([!28](https://github.com/climate-resource/bookshelf/issues/28)) Fix file retrieval and publishing on windows

## v0.2.1

### Changed

- ([!20](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/20)) Updated `DATA_FORMAT_VERSION` to `v0.2.1` in order to handle extra field
- ([!19](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/19)) Added gwp_context field to primap-hist for easier post processing
- ([!19](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/19)) Fixed the uploading of new editions

### Added

- ([!20](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/20)) Added the option to mark a version as "private". This version will not be listed, but can still be loaded if the version is specified.

## v0.2.0

### Changed

- ([!14](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/14)) Add sectoral information to CEDS and also support the initial CEDs release as part of Hoesly et al. 2018
- ([!17](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/17)) Added the concept of editions. Each time the processing changes the edition counter is incremented. The version identifier is reserved for the data source. This results in a breaking change of the data format which has been updated to `v0.2.0`.
- ([!16](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/16))  Updated `un-wpp@0.1.2` with some fixes to variable naming

## v0.1.0

### Changed

- ([!12](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/12)) Update primap-HIST to v0.2.0 to provide resources by region and by country
- ([!11](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/11)) Remove non-required dependencies from the  requirements
- ([!10](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/10)) Update issue and MR templates
- ([!7](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/7)) Renamed `LocalBook.metadata` to `LocalBook.as_datapackage`
- ([!6](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/6)) Renamed `Bookshelf.save` to `Bookshelf.publish`

### Added

- ([!15](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/15)) Add `un-wpp@v0.1.0`
- ([!13](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/13)) Add `ceds@0.0.1`
- ([!9](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/9)) Add `wdi@v0.1.1`
- ([!8](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/8)) Add `primap-hist@v0.1.0`
- ([!7](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/7)) Add `Bookshelf.list_versions`
- ([!6](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/6)) Add save CLI command
- ([!5](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/5)) Add CLI tool, `bookshelf` and CI test suite for notebooks
- ([!4](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/4)) Add NotebookMetadata schema and an example notebook with documentation
- ([!3](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/3)) Add ability to upload Books to a remote bookshelf
- ([!2](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/2)) Add precommit hooks and test coverage to the CI
- ([!1](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/1)) Add bandit and mypy to the CI
- Initial project setup
