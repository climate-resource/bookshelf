# API reference

These pages document the Python API of the `bookshelf` package.
Import every name from the top-level package, for example `from bookshelf import Bookshelf`.

| Page                      | Covers                                                          |
| ------------------------- | --------------------------------------------------------------- |
| [Bookshelf](bookshelf.md) | The client that finds volumes, resolves books and corrects them |
| [Volumes](volumes.md)     | A volume and the versions and editions it publishes             |
| [Books](books.md)         | A published book and the entries it indexes                     |
| [Resources](resources.md) | The bytes behind an entry, read as frames or files              |
| [Errors](errors.md)       | The exceptions a caller can catch                               |
| [Cache](cache.md)         | The local content cache that downloads read through             |
| [Legacy (0.4)](legacy.md) | The deprecated 0.4 consumer API                                 |

## What semver covers

Versions follow [Semantic Versioning](https://semver.org/) for the Python API listed in this section.
A breaking change to any of it lands only in a new major version,
after a release that deprecates it with a warning.
Adding a name, a keyword argument with a default, or a field to a returned value type is not breaking.

The promised names in the `bookshelf` package are:

- The client: `Bookshelf`.
  Its constructor, except the `transport` test seam,
  and the methods `close`, `ensure_authenticated`, `search_volumes`, `volume`, `book`,
  `resource`, `resource_by_hash` and `correct_book`.
- Handles: `Volume`, `Book`, `BookEntry` and `Resource`.
  A handle is obtained from a client, for example `bs.book(...)`, and is not built directly.
  Its methods and attributes are promised, but its constructor is not.
- Values: `ResourceInfo`, `DataPreview`, `ResourceType`, `Visibility`, `Identity`, `VolumeSummary`,
  `VolumeSearchResults`, `Facets`, `Facet`, `FacetValue`, `SeriesMetadata`, `BookCorrection`,
  `Problem`, `ItemError` and `CacheSummary`.
- The cache: `ContentCache`, with the members on the [Cache](cache.md) page.
- Errors: `BookshelfError` and every subclass on the [Errors](errors.md) page.
  That includes `PartialRegistrationError` and the publisher errors,
  `InvalidBundleError`, `InvalidRecipeError`, `InvalidReferenceError`, `RecordingError` and `RecordRefusedError`,
  so an `except` clause naming one keeps working.
  An attribute that returns a generated model or a producer type,
  such as `PartialRegistrationError.successful_outcomes`, is provisional.
- Metadata: `__version__`, `PRODUCTION_API_URL` and `OPENAPI_VERSION`.

Beyond the root package:

- `bookshelf.auth`, every name in its `__all__`.
- `bookshelf.legacy`, which stays until bookshelf 2.0 removes it.

`ResourceType`, `Visibility` and the other enumerated values are open.
A value a newer platform adds arrives as a member of its own rather than an error,
so compare with the named members and keep a fallback for the rest.

The API is synchronous.
Async code calls it through `asyncio.to_thread`,
as [Reading asynchronously](../how-to-guides/read_asynchronously.py) shows.

## Outside the promise

Anything not listed above can change in any release, even when it is importable.
That includes:

- The `bookshelf` command line interface.
  Its commands, options, output and exit codes may change between minor versions,
  so scripts that need stability should call the Python API instead.
- The bundle and recipe formats, which follow their own schema versions rather than the package version.
  See [the bundle format](../explanation/bundle-format.md) and [the recipe format](../explanation/recipe-format.md).
- The layout of the cache directory and the stored credentials file, which are private to the SDK.
- Underscore-prefixed modules and names, such as `bookshelf._core`.
- The generated API models, which track the platform contract.
  They are private, and some provisional producer methods still return them.
- Handle constructors, which take the private client and generated models.
- The producer surface, which is exported but still settling.
  That covers `setup`, `Activity`, `DraftBook`, `RegisterItem`, `Used`,
  `RegistrationSuccess` and `RegistrationFailure`.
  It also covers the `Bookshelf` methods `activity`, `draft_book`, `register_external`, `register_file`,
  `create_volume`, `get_or_create_volume`, `update_volume`, `delete_volume`, `update_draft`, `discard_draft`
  and `replay_bundle`, some of which still return generated models.
- `bookshelf.publisher`, which drives recording, replaying and publishing bundles, and its submodules.
  Its errors are the exception, because they are promised from the root package.
