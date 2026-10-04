# Configuration

Constructor arguments take precedence over ambient configuration,
so a value passed to `Bookshelf` or `AsyncBookshelf`
always beats the matching environment variable.

## Choosing a deployment

`base_url=` names the API deployment a client talks to.
Pass it when the deployment must be explicit, for example in a script that runs against staging.
Without it, the SDK reads `$BOOKSHELF_URL`, then falls back to a built-in default.
`bookshelf.PRODUCTION_API_URL` names the production deployment, which is the default.

| Variable        | Effect                                                                                |
| --------------- | ------------------------------------------------------------------------------------- |
| `BOOKSHELF_URL` | The API deployment to use. `BOOKSHELF_API_URL` is a deprecated alias, removed in 2.0. |

Stored credentials are scoped to a deployment,
so pointing a client at staging never sends it a production login.

`BOOKSHELF_REMOTE` named the 0.4 S3 bucket.
It is ignored now, and setting it raises a warning pointing at `BOOKSHELF_URL`.

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

| Variable                   | Effect                                                                                              |
| -------------------------- | --------------------------------------------------------------------------------------------------- |
| `BOOKSHELF_CACHE_DIR`      | Moves the local content cache. `BOOKSHELF_CACHE_LOCATION` is a deprecated alias, removed in 2.0.    |
| `BOOKSHELF_CACHE_BOOK_TTL` | Seconds a remembered pinned edition is trusted before it is checked again. The default is one hour. |

`book_ttl=` on `Bookshelf` and `AsyncBookshelf` overrides `BOOKSHELF_CACHE_BOOK_TTL` for one client.
The check also refreshes the edition's metadata and visibility, so `book_ttl=0` always reads them live.
`book(..., refresh=True)` skips the remembered edition and fetches it and its entries afresh.
`bookshelf cache` inspects and clears the cache.
