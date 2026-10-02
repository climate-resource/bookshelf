**From a 1.0 beta or release candidate.**
The breaking changes below are listed per pull request.
The ones most likely to need action are:

- Bundles are recorded at schema 3.10, and a bundle recorded by b18 or later still loads.
- A recipe has `volume:`, `defaults:`, `build:` and `books:` sections, and every book states its own `license`.
- `bookshelf validate --json`, `search --json` and `auth list --json` changed shape.
- A refused `record` parameter and a malformed base URL now exit 2.
- A recipe `uri` input over `http://` is refused, so it has to move to `https://`.
- Methods that returned generated models now return SDK-owned types.

The `bookshelf` command line interface, its exit codes and its JSON output are outside the
[semantic versioning promise](api/index.md#outside-the-promise), so they can change in a minor release.
