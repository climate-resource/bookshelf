# Configuration

Constructor arguments take precedence over ambient configuration,
so a value passed to `Bookshelf`, `AsyncBookshelf` or `BookshelfClient`
always beats the matching environment variable.

## Choosing a deployment

`base_url=` names the API deployment a client talks to.
Pass it when the deployment must be explicit, for example in a script that runs against staging.
Without it, the SDK reads `$BOOKSHELF_URL`, then falls back to a built-in default.

| Variable        | Effect                                                                  |
| --------------- | ----------------------------------------------------------------------- |
| `BOOKSHELF_URL` | The API deployment to use. `BOOKSHELF_API_URL` is accepted as an alias. |

Stored credentials are scoped to a deployment,
so pointing a client at staging never sends it a production login.

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

`auth=` on the client overrides every one of these,
and `auth=None` stays unauthenticated even when a credential is present.

Credentials written by `bookshelf auth login` live on disk rather than in the environment.
See [where credentials are stored](authentication.md#where-credentials-are-stored).

## Caching

Downloaded resources are cached by content hash, so a repeated read costs no download.

| Variable                   | Effect                                                                             |
| -------------------------- | ---------------------------------------------------------------------------------- |
| `BOOKSHELF_CACHE_DIR`      | Moves the local content cache. `BOOKSHELF_CACHE_LOCATION` is accepted as an alias. |
| `BOOKSHELF_CACHE_BOOK_TTL` | Lifetime of the local cache for a book. The default is one day.                    |

`bookshelf cache` inspects and clears the cache.
