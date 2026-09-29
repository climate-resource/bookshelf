# API reference

These pages list the stable public API of the `bookshelf` package.
Everything documented here follows [Semantic Versioning](https://semver.org/),
so a breaking change to any of it only lands in a new major version.

Import every name from the top-level package, for example `from bookshelf import Bookshelf`.

| Page                         | Covers                                               |
| ---------------------------- | ---------------------------------------------------- |
| [Bookshelf](bookshelf.md)    | The client that finds volumes and resolves books     |
| [Volumes](volumes.md)        | A volume and the versions and editions it publishes  |
| [Books](books.md)            | A published book and the entries it indexes          |
| [Resources](resources.md)    | The bytes behind an entry, read as frames or files   |
| [Errors](errors.md)          | The exceptions a caller can catch                    |
| [Cache](cache.md)            | The local content cache that downloads read through  |
| [Legacy (0.4)](legacy.md)    | The deprecated 0.4 consumer API                      |

The package also exports these names, which have no page of their own:

- `PRODUCTION_API_URL` and `STAGING_API_URL` name the two deployments.
- `__version__` is the installed package version.
- `OPENAPI_VERSION` is the version of the platform API contract the SDK was generated from.
- `uuid7` mints a time-ordered UUID.

## Outside the promise

Anything not on these pages can change in any release, even when it is importable.
This includes:

- Underscore-prefixed modules, such as `bookshelf._core`, are internal.
- The producer surface is exported but sits outside the promise for now.
  That covers `setup`, `run_record`, `replay_bundle`, `replay_bundle_sync`, `Activity`, `DraftBook`,
  `RegisterItem`, `Used` and their async and result counterparts.
  It also covers `Bookshelf.activity`, `Bookshelf.draft_book` and the volume and draft management methods.
- `bookshelf.publisher` drives recording, replaying and publishing bundles, and is not covered.
- `bookshelf.models` holds the generated API models.
  Methods above still return some of these, but their fields track the platform API.
- The `transport` and `async_transport` arguments exist for tests.
- The `bookshelf` command line interface is not covered.
