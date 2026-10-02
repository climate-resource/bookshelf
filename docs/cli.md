# Command line

`bookshelf` is the command line interface installed with the package.
It is a machine interface first, so scripts, CI jobs and agents can drive it:

- Payload goes to stdout and diagnostics go to stderr.
- Nothing changes when a terminal is attached, so piped output matches what you see.
- The exit code says what went wrong, as listed under [exit codes](#exit-codes).

[Addressing](addressing.md) covers how a command names a volume, a book or an entry.
[Configuration](configuration.md) lists the environment variables it reads.

## Stability

The CLI is outside the semantic versioning promise that covers the Python API.
Commands, flags, `--json` keys and exit codes may change in a minor release.
Every such change is listed in the [changelog](changelog.md).
Pin the `bookshelf` version a script depends on, and read the changelog before raising it.

## Output

Every command that reports something takes `--json`.
Without it the same fields print as aligned rows, under labels derived from the JSON keys.

- A command that reports one thing prints one JSON document.
- A listing (`search`, `auth list`) prints one JSON object per line, and nothing when it is empty.
- `search --json` ends with one `{"page": {...}}` line carrying `offset`, `limit`, `returned`, `total`
  and `next_offset`, which is `null` on the last page.
- Errors are plain text on stderr, with or without `--json`.

The `--json` keys follow a few rules:

- A byte count ends in `_bytes`: `size_bytes` for one file, `total_size_bytes`, `max_size_bytes`
  and `freed_size_bytes` for the cache.
- A hash is `content_hash`, written `sha256:<hex>`.
- A count ends in `_count`, such as `resource_count` and `entry_count`.
- A named file in a book is an entry, so a book lists its `entries`.
- A moment is UTC ISO 8601 to the second, with a `Z` suffix.

`bookshelf auth token` and `bookshelf cache path` print a bare value by default,
so they drop straight into shell interpolation.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | success |
| 1 | any other failure, including a bug worth reporting |
| 2 | usage: bad arguments, a malformed address, or unusable local setup |
| 3 | no accepted credential: log in, or refresh the one in play |
| 4 | the credential lacks a permission |
| 5 | the volume, book, entry or resource does not exist |
| 6 | network, gateway or server failure, worth retrying |
| 7 | the bundle is malformed or refused |
| 8 | the request conflicts with what the platform holds |
| 9 | the server answered outside the API contract: upgrade bookshelf |

Some cases worth knowing:

- A bundle directory that does not exist is a usage error (2), where one that exists but is malformed is 7.
- A build that cannot read its code ref from git, for example outside a repository, is a usage error (2).
- Incomplete credential settings, such as `BOOKSHELF_CLIENT_ID` without its secret, are a usage error (2).
- A credentials file written by a newer `bookshelf` is read but never written, so a login or logout
  against it exits 2.
- A rate limit the retries could not wait out is a network failure (6).

`bookshelf --help` prints the same table.

## Credentials file

`bookshelf auth login` stores credentials in a file under your user configuration directory.
Its format is private and may change in any release, so do not read or write it directly.
Use `bookshelf auth list --json` to see what is stored, and `bookshelf auth token` to get a usable token.

A file written by a newer `bookshelf` is read for whatever this version understands, and never overwritten,
so going back to an older version cannot log the newer one out.
Logging in or out with the older version fails with exit code 2 until you upgrade.

## Command reference

Hidden commands, such as `preview` which the feedstock CI workflow runs, are left out.

<!-- BEGIN GENERATED REFERENCE: make cli-reference -->

### `bookshelf`

Bookshelf data platform CLI.

```console
$ bookshelf [OPTIONS] COMMAND [ARGS]...
```

Options:

- `--api-url <str>`: Deployment to act against. Defaults to $BOOKSHELF_URL.
- `--version`: Print the installed version and exit.

### `bookshelf search`

Search volumes with free text and filters, which combine with AND.

```console
$ bookshelf search [OPTIONS] [query]
```

Arguments:

- `query`: Free text over name, title and summary. Optional.

Options:

- `--topic <str>`: Topic the volume must carry.
- `--keyword <str>`: Keyword the volume must carry.
- `--region <str>`: Region the volume must cover.
- `--publisher <str>`: Publisher organisation.
- `--licence, --license <str>`: SPDX licence identifier.
- `--coverage-year <int>`: Year the volume's data must cover.
- `--type <timeseries|geospatial|tabular|document|binary|figure>`: Resource type the volume contains.
- `--deprecated / --no-deprecated`: Restrict to deprecated or to active volumes. Omitted means both.
- `--limit <int range>`: Maximum results.  [default: 20; 1&lt;=x&lt;=1000]
- `--offset <int range>`: Results to skip.  [default: 0; x>=0]
- `--facets`: List every valid filter value instead of searching. Takes no query or filters.
- `--json`: One JSON object per result, then one 'page' object with the totals and next offset.

### `bookshelf show`

Resolve one address and describe what is there, at whatever depth it is given.

```console
$ bookshelf show [OPTIONS] {ADDRESS}
```

Arguments:

- `ADDRESS`: volume[@version[_eNNN]][/entry], or the bookshelf:// reference naming the same thing.  [required]

Options:

- `--json`: Emit the description as JSON.

### `bookshelf record`

Execute a build file and record it into a reviewable bundle.

```console
$ bookshelf record [OPTIONS] [build]
```

Arguments:

- `build`: Standalone Jupytext build file. Defaults to the recipe's notebook.

Options:

- `--recipe <path>`: Sectioned Bookshelf recipe.  [default: bookshelf.yaml]
- `--bundle <path>`: Bundle directory to write.  [default: bundle]
- `--book VERSION`: Required. Version to build, naming a book under 'books:' in the recipe.
- `-p, --parameter KEY=VALUE`: Value for a top-level assignment in the build file, read as YAML. Repeatable.
- `--force`: Replace an existing bundle directory.
- `--json`: Emit the summary as JSON.

### `bookshelf validate`

Assert a recorded bundle is a replayable published book.

```console
$ bookshelf validate [OPTIONS] [bundle]
```

Arguments:

- `bundle`: Bundle directory to validate.  [default: bundle]

Options:

- `--json`: Emit the summary as JSON.

### `bookshelf publish`

Replay a recorded bundle to publish it, converging on one edition.

```console
$ bookshelf publish [OPTIONS] [bundle]
```

Arguments:

- `bundle`: Bundle directory to replay.  [default: bundle]

Options:

- `--dry-run`: Report what would be sent without sending it. Resolves no edition.
- `--json`: Emit the summary as JSON.

### `bookshelf discard`

Delete a draft edition, so a publish that failed validation leaves no debris.

Only a draft can be discarded.
A published book is protected by the API, and the CLI refuses one before it asks.

```console
$ bookshelf discard [OPTIONS] {address}
```

Arguments:

- `address`: Draft edition to discard, as volume@version_eNNN.  [required]

Options:

- `--json`: Emit the outcome as JSON.

### `bookshelf upload`

Upload a file as a standalone input and print the bookshelf URI that names it.

The URI is bookshelf://sha256/&lt;hex>, which a recipe declares under resources: as its uri.
The file is readable by your organisation alone.

```console
$ bookshelf upload [OPTIONS] {file}
```

Arguments:

- `file`: File to upload.  [required]

Options:

- `--type <timeseries|geospatial|tabular|document|binary|figure>`: Resource type the file registers under. Never inferred from the name.  [required]
- `--name <str>`: Resource name. Defaults to the file name, flattened.
- `--description <str>`: What the file is.
- `--tag <str>`: Catalogue tag. Repeatable.
- `--json`: Emit the outcome as JSON.

### `bookshelf auth`

Manage authentication for the Bookshelf API.

```console
$ bookshelf auth [OPTIONS] COMMAND [ARGS]...
```

### `bookshelf auth login`

Log in: through WorkOS as a human, or as an agent with --agent.

```console
$ bookshelf auth login [OPTIONS]
```

Options:

- `--agent`: Register an agent identity instead of a human login.
- `--claim`: Run the claim ceremony so a human binds the identity.
- `--email <str>`: Email the approving human signs in with. Required with --claim.
- `--no-browser`: For a box that cannot open a browser.
- `--json`: Emit the credential summary as JSON.

### `bookshelf auth token`

Print the current access token to stdout and nothing else.

```console
$ bookshelf auth token [OPTIONS]
```

Options:

- `--json`: Emit the token and its deployment as JSON.

### `bookshelf auth whoami`

Report the identity in play and which resolution step supplied it.

```console
$ bookshelf auth whoami [OPTIONS]
```

Options:

- `--offline`: Report the stored credential without calling the API.
- `--json`: Emit the report as JSON.

### `bookshelf auth logout`

Revoke and clear stored credentials. Local state is cleared even when revocation fails.

```console
$ bookshelf auth logout [OPTIONS]
```

Options:

- `--all`: Clear every stored identity for every deployment.
- `--no-revoke`: Skip server-side revocation and only clear local state.
- `--json`: Emit the outcome as JSON.

### `bookshelf auth list`

List every stored identity, marking the active one per deployment.

```console
$ bookshelf auth list [OPTIONS]
```

Options:

- `--json`: Emit one JSON object per identity.

### `bookshelf auth switch`

Make a stored identity active without re-authenticating.

```console
$ bookshelf auth switch [OPTIONS] {identity}
```

Arguments:

- `identity`: The identity to make active, as shown by 'auth list'.  [required]

Options:

- `--json`: Emit the identity as JSON.

### `bookshelf cache`

Manage the local content cache.

```console
$ bookshelf cache [OPTIONS] COMMAND [ARGS]...
```

### `bookshelf cache info`

Show cache size, entry count, age range and the configured cap.

```console
$ bookshelf cache info [OPTIONS]
```

Options:

- `--json`: Emit the summary as JSON.

### `bookshelf cache prune`

Evict oldest entries until the cache fits the cap.

```console
$ bookshelf cache prune [OPTIONS]
```

Options:

- `--max-bytes <int range>`: Cap to prune the cache down to.  [default: 5368709120; x>=0]
- `--json`: Emit the result as JSON.

### `bookshelf cache clear`

Remove everything. Requires --yes, so a cache is never wiped by accident.

```console
$ bookshelf cache clear [OPTIONS]
```

Options:

- `--yes`: Confirm removal of every cached entry.
- `--json`: Emit the result as JSON.

### `bookshelf cache path`

Print the cache directory as a bare string, for shell interpolation.

```console
$ bookshelf cache path [OPTIONS]
```

Options:

- `--json`: Emit the path as JSON.

### `bookshelf volume`

Create, update and delete volumes.

```console
$ bookshelf volume [OPTIONS] COMMAND [ARGS]...
```

### `bookshelf volume create`

Create a volume, which a first publish into a new collection needs.

Creating needs WRITE and deleting needs ADMIN,
so you may not be able to delete what you create here.

```console
$ bookshelf volume create [OPTIONS] {name}
```

Arguments:

- `name`: Volume name, in alphanumerics, hyphens and underscores.  [required]

Options:

- `--licence, --license <str>`: SPDX licence identifier.  [required]
- `--description <str>`: Long-form description.
- `--author <str>`: Name of somebody who made the data. Repeatable.
- `--maintainer <str>`: Name of somebody who maintains the feedstock. Repeatable.
- `--metadata <path>`: JSON file holding arbitrary volume metadata.
- `--json`: Emit the volume as JSON.

### `bookshelf volume update`

Update a volume's metadata. Each field given replaces what is there, and the licence is fixed.

```console
$ bookshelf volume update [OPTIONS] {name}
```

Arguments:

- `name`: Volume to update.  [required]

Options:

- `--description <str>`: Long-form description.
- `--author <str>`: Name of somebody who made the data. Repeatable.
- `--maintainer <str>`: Name of somebody who maintains the feedstock. Repeatable.
- `--metadata <path>`: JSON file holding arbitrary volume metadata.
- `--json`: Emit the volume as JSON.

### `bookshelf volume delete`

Delete a volume and every book in it. This needs ADMIN, where creation needs WRITE.

```console
$ bookshelf volume delete [OPTIONS] {name}
```

Arguments:

- `name`: Volume to delete, with every book in it.  [required]

Options:

- `--yes`: Confirm the deletion, which is not reversible.
- `--json`: Emit the outcome as JSON.

<!-- END GENERATED REFERENCE -->
