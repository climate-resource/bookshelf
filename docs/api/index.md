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

## Outside the promise

Anything not on these pages can change in any release, even when it is importable.
This includes:

- underscore-prefixed modules, such as `bookshelf._core`.
- the producer surface: `Bookshelf.activity`, `Bookshelf.draft_book` and the volume and draft management methods.
- `bookshelf.publisher`, which drives recording, replaying and publishing bundles.
- `bookshelf.models`, the generated API models.
  Methods above still return some of these, but their fields track the platform API.
- the `transport` argument to `Bookshelf` and `AsyncBookshelf`, which exists for tests.
- the `bookshelf` command line interface.
