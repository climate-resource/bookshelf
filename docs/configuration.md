# Configuration

Constructor arguments take precedence over ambient configuration,
so a value passed to `Bookshelf`, `AsyncBookshelf` or `BookshelfClient`
always beats the matching environment variable.

## Choosing a deployment

`base_url=` names the API deployment a client talks to.
Pass it when the deployment must be explicit, for example in a script that runs against staging.
Without it, the SDK reads `$BOOKSHELF_URL`, then falls back to a built-in default.
`bookshelf.PRODUCTION_API_URL` and `bookshelf.STAGING_API_URL` name the two deployments,
so a script need not copy either URL.

| Variable        | Effect                                                                  |
| --------------- | ----------------------------------------------------------------------- |
| `BOOKSHELF_URL` | The API deployment to use. `BOOKSHELF_API_URL` is accepted as an alias. |

Stored credentials are scoped to a deployment,
so pointing a client at staging never sends it a production login.

`BOOKSHELF_REMOTE` named the 0.4 S3 bucket.
It is ignored now, and setting it raises a warning pointing at `BOOKSHELF_URL`.
`BOOKSHELF_USE_KEYCHAIN` chose the keychain credential store, which no longer exists.
It is ignored too, and setting it raises a warning.

## Credentials

These select which credential the client sends.
[Authentication](authentication.md) explains what each one is for
and the order they are tried in.

| Variable                     | Effect                                                                                         |
| ---------------------------- | ---------------------------------------------------------------------------------------------- |
| `BOOKSHELF_TOKEN`            | A bearer token, sent exactly as given and never refreshed.                                     |
| `BOOKSHELF_AUTH`             | Set to `github-actions` to read with the job's GitHub Actions OIDC token.                      |
| `BOOKSHELF_CLIENT_ID`        | An OAuth client ID, paired with `BOOKSHELF_CLIENT_SECRET`. Climate Resource's CI uses this.    |
| `BOOKSHELF_CLIENT_SECRET`    | The matching client secret.                                                                    |
| `BOOKSHELF_TOKEN_URL`        | The token endpoint the client credentials are exchanged at. Required alongside the pair above. |
| `BOOKSHELF_WORKOS_CLIENT_ID` | The WorkOS client ID for login and refresh. Production and staging have theirs built in.       |
| `BOOKSHELF_WORKOS_BASE_URL`  | The WorkOS API a login is made against. Defaults to `https://auth-api.climateresource.com.au`. |

`auth=` on the client overrides every one of these,
and `auth=None` stays unauthenticated even when a credential is present.

Credentials written by `bookshelf auth login` live on disk rather than in the environment.
See [where credentials are stored](authentication.md#where-credentials-are-stored).

## Caching

Downloaded resources are cached by content hash, so a repeated read costs no download.
The converters, `fetch()`, `download()` and `as_path()` all read through the same cache.
An external pointer is selected by the platform, because it has no cached file.
Cached content never expires, and the oldest entries are removed once the cache passes 5 GiB.

| Variable                   | Effect                                                                                             |
| -------------------------- | -------------------------------------------------------------------------------------------------- |
| `BOOKSHELF_CACHE_DIR`      | Moves the local content cache. `BOOKSHELF_CACHE_LOCATION` is accepted as an alias.                 |
| `BOOKSHELF_CACHE_BOOK_TTL` | Seconds a remembered pinned edition is trusted before it is checked again. The default is one hour. |

`book_ttl=` on `Bookshelf` and `AsyncBookshelf` overrides `BOOKSHELF_CACHE_BOOK_TTL` for one client.
The check also refreshes the edition's metadata and visibility, so `book_ttl=0` always reads them live.
`book(..., refresh=True)` skips the remembered edition and fetches it and its entries afresh.
`bookshelf cache` inspects and clears the cache.

## Read from the environment

The SDK also reads a few variables it does not own,
to tell how and where it is running.
Set them only to change that behaviour.

| Variable                                                          | Effect                                                                                                    |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `CI`                                                              | Any value but `0` or `false` marks a CI run: no login is offered, and an activity's `runner` is `ci`.     |
| `GITHUB_RUN_ID`                                                   | Names the GitHub Actions run, recorded as the activity's `runner` in the form `github-actions:<run id>`.  |
| `SSH_CONNECTION`, `SSH_TTY`                                       | Either one means a browser cannot reach this machine, so a login the SDK offers uses the device flow.     |
| `ACTIONS_ID_TOKEN_REQUEST_URL`, `ACTIONS_ID_TOKEN_REQUEST_TOKEN` | Where a GitHub Actions job fetches its OIDC token, for `BOOKSHELF_AUTH=github-actions` and previews.      |

Outside CI and GitHub Actions an activity's `runner` is `local`, so a recorded build never names the machine.
