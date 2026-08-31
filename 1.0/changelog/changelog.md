# Changelog

Versions follow [Semantic Versioning](https://semver.org/) (`<major>.<minor>.<patch>`).

Backward incompatible (breaking) changes will only be introduced in major versions
with advance notice in the **Deprecations** section of releases.


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

## bookshelf v1.0.0b2 (2026-08-31)

### Breaking Changes

- Changes two behaviours a caller can observe:

  - Serialising a `DataFrame` without the `dataframes` extra raises `DataFrameSupportError` rather than `ImportError`.
  - The SDK and the CLI now share one SemVer version ordering, so they agree on which book is the newest.
    This changes the order `list_books()` returns for volumes that publish prerelease versions.

  The SDK now follows a major rework to allow discovery facts to be attached to volumes, books and resources.

  - Removes `abstract` from the recipe's `defaults:` section.
    A dataset summary is `description`.
  - Sends `description` and `authors` inside the book's `discovery` object rather than beside it.
  - States the licence on every book.
    The API now requires a specific licence for each book rather than supporting defaults.

  Replaces the five-call publish sequence with the platform's one replay endpoint, `POST /v1/bundles/replay`:

  - Uploads the managed bytes then sends the whole bundle in one transactional request.
    A failure rolls all of it back.
  - Derives a recorded activity's id from its kind, code ref, config hash and parameters,
    rather than minting a fresh one per run.
    Recording the same build twice now writes the same manifest.
  - Adds `Bookshelf.replay_bundle` and its asynchronous counterpart,
    so the publisher drives the replay through the facade rather than through its transport.
  - Addresses every resource by its bundle-local name, which the platform maps to a tracking id itself.
  - Records `used` lineage as the names of resources the same bundle carries.
    Citing a resource the bundle does not carry now fails.
    A published resource reached through a `bookshelf://` reference is one of those,
    so a feedstock built on another book is currently broken.
    That loss is unintended and tracked by an xfail rather than accepted.
  - The server now calculates the seal.
  - Returns a `BundleReplayResponse` from `replay_bundle` and `replay_bundle_sync` rather than a draft book.
    `PublishOutcome` reports `converged`, `resource_count` and `dedupe_hits`,
    and reports `no-op` only for a converged replay that also wrote nothing.
  - Raises the bundle manifest to schema 3.0, which keys its resources by name.

  ([#136](https://github.com/climate-resource/bookshelf/pull/136))
- Removes the retired recipe and lock surface from `bookshelf.publisher`.
  The record then replay path replaces it. ([#162](https://github.com/climate-resource/bookshelf/pull/162))
- Moves `data_dictionary=` from book drafting and updating
  to `DraftBook.attach()` and `AsyncDraftBook.attach()`.
  Each book entry gains its own dictionary.
  Omitting the argument preserves an existing entry dictionary on re-attach, while an empty list clears it. ([#165](https://github.com/climate-resource/bookshelf/pull/165))
- Replaces the flat recipe with `volume:`, `defaults:`, `build:` and `books:` sections,
  and makes `bookshelf record --version` required.

  - The flat form no longer loads, and a recipe using it is rejected with a message naming the new shape.
  - `collection`, `authors` and `notebook` move under `volume:` and `build:`.
  - `books:` is a list, one entry per book, each stating its own `version:`.
    Two books claiming one version are rejected.
  - `defaults:` holds what every book starts from, and a book overrides any of it field by field.
  - The discovery fields move from `volume: discovery:` to `defaults:`, and sit flat there.
  - `visibility:` may be set under `defaults:` and is rejected under `build:`.
    It is `hidden` where neither states it.
  - Every book states its own `license`. A `license` under `volume:` is rejected.
  - `topics:` is gone. Use `keywords:`.
  - A resource states a `type` from the same set the platform registers a resource under.
  - A resource default is a template, so a book that never names the resource does not get it.
  - A book stating its own `path:` or `uri:` replaces the default's location rather than joining it.
  - Unknown keys are rejected at every level.
  - `--version` selects the book to record, and `bookshelf.setup()` is called without a version.
  - `ResolvedVersion` is now `ResolvedBook`, and `VersionSpec` is now `BookSpec`.

  ([#179](https://github.com/climate-resource/bookshelf/pull/179))
- Replaces the SDK's `logical_key` with `name`.

  - `logical_key=` becomes `name=` on `Used`, `RegisterItem`, `register`, `register_many`,
    `register_external` and the recording adapters.
  - `Used(name=...)` resolves only against the resources registered by the same request,
    so a resource from an earlier build has to be referenced by its tracking id.
  - `GET /v1/resources` trades its `logical_key` filter for `volume`, `name` and `hash`.
  - Bumps `BUNDLE_SCHEMA_VERSION` to `2.0`.

  ([#189](https://github.com/climate-resource/bookshelf/pull/189))
- Refreshes the vendored API contract onto the platform's bundle replay endpoint.

  - `draft_book(citation_doi=...)` is removed, along with `citation_doi` on the bundle's book framing.
    Pass `discovery={"doi": ...}` instead.
  - `RegistrationOutcome.aliased_to` is removed. `tracking_id` is canonical on every status.

  ([#190](https://github.com/climate-resource/bookshelf/pull/190))
- `resolve_resource` now takes a `register_file` sink alongside `register_external`.
  A checked-in resource records its bytes through it, so a caller driving the resolver
  directly has to supply one. ([#205](https://github.com/climate-resource/bookshelf/pull/205))

### Deprecations

- Kept the 0.4 consumer API working on top of the platform, with a `DeprecationWarning` at every call.

  - `bookshelf.BookShelf` and `bookshelf.LocalBook` still resolve,
    and live in `bookshelf.legacy` alongside the old `UnknownBook`, `UnknownVersion` and `UnknownEdition` errors.
  - `BOOKSHELF_CACHE_LOCATION` is honoured as a fallback for `BOOKSHELF_CACHE_DIR`,
    and `BOOKSHELF_REMOTE` or a `remote_bookshelf` URL now warns instead of being silently ignored.
  - `as_long_df(legacy_columns=True)` reproduces the 0.4 long format.

  ([#203](https://github.com/climate-resource/bookshelf/pull/203))

### Features

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
  - The asynchronous facade carries the same methods.

  ([#142](https://github.com/climate-resource/bookshelf/pull/142))
- Adds `data_dictionary=` on `DraftBook.attach()`, so a producer can declare what a book's columns mean.
  The dictionary is recorded in the bundle manifest and sent on replay,
  so it survives a record and replay round trip. ([#145](https://github.com/climate-resource/bookshelf/pull/145))
- Publishes the bundle format as a specification at `docs/explanation/bundle-format.md`.
  It describes the bytes on disk rather than the Python interface,
  so an implementation in another language can be written from it. ([#164](https://github.com/climate-resource/bookshelf/pull/164))
- Adds catalogue discovery to the `Bookshelf` and `AsyncBookshelf` facades.

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
- Replaces the legacy V1 consumer library with the public Bookshelf SDK.
  Retires the separate `bookshelf-producer` distribution,
  because its publishing capabilities now live in the SDK. ([#204](https://github.com/climate-resource/bookshelf/pull/204))
- Adds `source_url` metadata to a checked-in resource, linking to the commit the file was read at.
  The bytes are re-hosted, so this is what ties them back to the repository they came from.
  The link is omitted when the file itself is uncommitted or has moved away from the commit,
  and when the repository states no origin, holds no commit, or sits on an unrecognised forge.
  A change elsewhere in the clone does not cost the link. ([#205](https://github.com/climate-resource/bookshelf/pull/205))

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
  CI regenerates and diffs the result, so the sync and async halves of the client can no longer drift,
  and a new API operation cannot be silently left unexposed. ([#154](https://github.com/climate-resource/bookshelf/pull/154))
- Retires the seams that only ever had one adapter.
  `retry` and `cache` are gone from `Bookshelf`, `AsyncBookshelf` and `BookshelfClient`,
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
- Records the pyarrow writer version in the bundle manifest header, under a new optional `writer` block,
  and bumps the manifest schema to `1.1`.
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
- Points the default API URL at the staging deployment,
  because that is the only deployment serving data today.
  The production default returns to `PRODUCTION_API_URL` in the 1.0.0 release,
  so feedstocks do not need a deployment-specific override in the meantime. ([#204](https://github.com/climate-resource/bookshelf/pull/204))

### Bug Fixes

- Fixes a batch of defects found in review of the SDK adoption:

  - `as_long_df` no longer raises `KeyError` on a wide frame that carries year columns and no dimensions.
  - Selects the staging WorkOS client from a host label rather than any occurrence of the word in the API URL.
  - The browser login no longer fails when an incidental request reaches the loopback callback
    before the redirect.
  - An unparseable server timestamp now surfaces as a validation error rather than a bare `ValueError`.
  - Pairs batch registration outcomes with their request items by the server-reported index.
  - Raises a typed error when a registration response commits nothing, instead of `IndexError`.
  - Reads a cached resource off the event loop on the async `fetch` path.
  - Repairs naive timestamps when listing resources, so both resource endpoints agree.
  - A browser login no longer fails because a recent one still holds a port in `TIME_WAIT`.
  - The async book entry repr reports the resource type it has already fetched, rather than "unknown".
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
- Keeps access tokens, refresh tokens and identity assertions in the OS keychain when it can hold them,
  writing them to `credentials.json` only when the keychain is unavailable.
  Writes the credential store atomically. ([#150](https://github.com/climate-resource/bookshelf/pull/150))
- Hashes a freshly downloaded resource off the event loop when fetching asynchronously.
  Verification previously ran inline, so a large download stalled every other task on the loop for the duration of the hash. ([#155](https://github.com/climate-resource/bookshelf/pull/155))
- Confines the SDK retry policy to requests that are safe to replay,
  so a transient 5xx can no longer duplicate a write.

  - Only idempotent methods are retried on a 5xx. A `POST` or a `PATCH` now surfaces the error to the caller.
  - A network failure on a write is only retried when the connection never came up.
  - `501` and `505` are no longer retried on any method.

  ([#156](https://github.com/climate-resource/bookshelf/pull/156))
- Raises a typed `DataFrameSupportError` with an install hint from `as_polars()` and `as_arrow()`
  when the `dataframes` extra is missing, instead of a bare `ImportError`. ([#157](https://github.com/climate-resource/bookshelf/pull/157))
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
- Records a checked-in `path:` resource as managed bytes rather than as a pointer at its repository
  path. The platform only accepts an `https` pointer it can fetch again, so a bundle carrying a
  checked-in input could be recorded and validated but never published. ([#205](https://github.com/climate-resource/bookshelf/pull/205))

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

### Trivial/Internal Changes

- [#160](https://github.com/climate-resource/bookshelf/pull/160), [#178](https://github.com/climate-resource/bookshelf/pull/178), [#196](https://github.com/climate-resource/bookshelf/pull/196), [#197](https://github.com/climate-resource/bookshelf/pull/197)


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

  ([#65](https://github.com/climate-resource/bookshelf/issue/65))

### Features

- Added Climate Resource's NDCs dataset to the bookshelf ([#56](https://github.com/climate-resource/bookshelf/issue/56))
- Add a functions to add long format data and compressed files ([#58](https://github.com/climate-resource/bookshelf/issue/58))
- Add a functions to get long format data from the book ([#59](https://github.com/climate-resource/bookshelf/issue/59))
- Added 20240318 version of CAT dataset to the bookshelf ([#64](https://github.com/climate-resource/bookshelf/issue/64))
- Deploy documentation automatically via the CI ([#109](https://github.com/climate-resource/bookshelf/pull/109))

### Improvements

- When running a notebook, the files were verified through data content hash code rather than file name hash code ([#60](https://github.com/climate-resource/bookshelf/issue/60))
- Migrate to github ([#106](https://github.com/climate-resource/bookshelf/pull/106))
- Removed the primap-hist dataset from the repository.

  This dataset has been migrated to be a standalone dataset at
  [climate-resource/bookshelf-primap-hist](https://github.com/climate-resource/bookshelf-primap-hist). ([#111](https://github.com/climate-resource/bookshelf/pull/111))
- Moved the `bookshelf` package to the `packages/` directory to improve the DX when working with the repository.
  This has no user-facing impact. ([#112](https://github.com/climate-resource/bookshelf/pull/112))
- Replaced deprecated dependency `appdirs` with `platformdirs` ([#108](https://github.com/climate-resource/bookshelf/pull/108))
- Pin bookshelf version for producer ([#110](https://github.com/climate-resource/bookshelf/pull/110))


### Bug Fixes

- resolve the issue where the upload and download files have rows in a different order. ([#63](https://github.com/climate-resource/bookshelf/issue/63))

### Improved Documentation

- Updated the volume creation documentation ([#114](https://github.com/climate-resource/bookshelf/pull/114))
- Add example notebooks to docs ([#61](https://github.com/climate-resource/bookshelf/issue/61))
- Migrated documentation to use [mkdocs](https://www.mkdocs.org/).
  This allows us to write documentation in only MarkDown,
  instead of mixing reStructuredText and Markdown. ([#66](https://github.com/climate-resource/bookshelf/issue/66))

### Trivial/Internal Changes

- [#107](https://github.com/climate-resource/bookshelf/pull/107)
- [#113](https://github.com/climate-resource/bookshelf/pull/113)
- [#65](https://github.com/climate-resource/bookshelf/pull/65)


## bookshelf v0.3.0 (2024-01-31)


### Features

- * Added legacy GDP results from Excel NDC Tool. ([#42](https://github.com/climate-resource/bookshelf/bookshelf/issue/42))
- Add an updated version of the World Bank's World Development Indicators (v23). The `wdi` book has also been
  updated to edition 2. ([#43](https://github.com/climate-resource/bookshelf/bookshelf/issue/43))
- * Added greenhouse gas emissions data from Climate Action Tracker (CAT).
  * Added historical greenhouse gas emission data and projection data from PBL Netherlands Environmental Assessment Agency.
  * Added estimated energy sector CO2 emissions data from International Energy Agency.

  ([#45](https://github.com/climate-resource/bookshelf/bookshelf/issue/45))
- Add a function to display the structure of a dataset ([#48](https://github.com/climate-resource/bookshelf/bookshelf/issue/48))
- Add data dictionary to schema ([#49](https://github.com/climate-resource/bookshelf/bookshelf/issue/49))
- Add data dictionary verification ([#50](https://github.com/climate-resource/bookshelf/bookshelf/issue/50))
- Added NGFS3 emissions data. ([#53](https://github.com/climate-resource/bookshelf/bookshelf/issue/53))

### Bug Fixes

- Fix to the schema for datasets to allow no files to be specified ([#47](https://github.com/climate-resource/bookshelf/bookshelf/issue/47))
- Re-add notebook tests to CI

  Updated primap-hist and primap-ssp-downscaled editions to update reflect the renaming of `turkey` to `Türkiye` ([#51](https://github.com/climate-resource/bookshelf/bookshelf/issue/51))

### Trivial/Internal Changes

- [#55](https://github.com/climate-resource/bookshelf/bookshelf/issue/55)


## bookshelf v0.2.4 (2023-08-14)


### Features

- Added the Biennial Reports Common Table Format data reported by Annex-I parties as un-br-ctf.

  For now, contains the GHG projections data. ([#38](https://github.com/climate-resource/bookshelf/bookshelf/issue/38))

### Bug Fixes

- Add CLI entrypoint that was inadvertently missed when migrating to the new copier template. ([#39](https://github.com/climate-resource/bookshelf/bookshelf/issue/39))
- Fixed the un-br-ctf dataset, now includes a lot more data.

  Version 2023-08, edition 1 of the un-br-ctf dataset is to be considered broken, always
  use edition 2 instead. ([#40](https://github.com/climate-resource/bookshelf/bookshelf/issue/40))

### Improved Documentation

- Added documentation about generating and using new versions of Books locally. ([#41](https://github.com/climate-resource/bookshelf/bookshelf/issue/41))


## bookshelf v0.2.3 (2023-07-28)


### Features

- Add PRIMAP downscaled SSPs dataset: `primap-ssp-downscaled` ([#34](https://github.com/climate-resource/bookshelf/bookshelf/issue/34))
- Migrate to the common Climate Resource copier template

  Major changes include adding support for the use of `towncrier` for managing the changelogs and `liccheck` for verifying
  the compliance of any project dependencies. ([#35](https://github.com/climate-resource/bookshelf/bookshelf/issue/35))

### Improvements

- Use original region abbreviations in PRIMAP-hist. Bumps `primap-hist` to edition 4. ([#34](https://github.com/climate-resource/bookshelf/bookshelf/issue/34))
- Extract SSP marker scenarios in addition to the existing baseline scenarios. Bumps `primap-ssp-downscaled` to ed.2 ([#36](https://github.com/climate-resource/bookshelf/bookshelf/issue/36))

### Bug Fixes

- Convert PRIMAP-hist to units of the form `kt X / yr` to be consistent. Bumps `primap-hist` to ed.3 ([#32](https://github.com/climate-resource/bookshelf/bookshelf/issue/32))


## v0.2.2

### Added

- ([!27](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/27)) Add sphinx-based documentation
- ([!26](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/26)) Add `force` option to the publish CLI command to upload data even if a matching edition already exists
- ([!25](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/25)) Add primap-hist v2.4.1 and v2.4.2

### Changed

- ([!29](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/29)) Move `python-dotenv` from a development dependency to a core dependency
- ([!23](https://gitlab.com/climate-resource/bookshelf/bookshelf/merge_requests/23)) Fix CEDs unit names for all resources. Bumps `ceds` to ed.3

### Fixed

- ([!28](https://github.com/climate-resource/bookshelf/bookshelf/issue/28)) Fix file retrieval and publishing on windows

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
