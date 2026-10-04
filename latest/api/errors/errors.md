# Errors

Every error the SDK raises for a failed operation subclasses `BookshelfError`.
Each class below is importable from `bookshelf`.

Misusing the API raises Python's own `TypeError` or `ValueError` instead,
for example passing an argument a resource type does not accept.
These signal a bug in the calling code rather than a condition to handle.

A success response whose JSON does not match the operation's schema raises `ContractError`.
It means the platform and this SDK disagree about the contract, so upgrading bookshelf is the first thing to try.

## Not found

A volume, version, book, entry or resource that does not exist raises `NotFoundError`,
whether the platform answered 404 or the SDK settled the lookup locally.
`NotFoundError` is also a `LookupError`.

Looking up an entry a book does not index raises `EntryNotFoundError`.
It is also a `KeyError`, so `book["name"]` behaves like any other mapping.
Looking up a version a volume has not published raises `VersionNotFoundError`,
which is also a `KeyError`, so `volume["version"]` behaves the same way.

Filtering or ordering on a column the data does not have raises `SelectionError`,
which is also a `KeyError`.
So does a filter value the column cannot be read as, and a selection the platform refuses.

## HTTP responses

An HTTP error response raises an `APIError` subclass chosen by status,
so a caller can catch `NotFoundError` or `ConflictError` rather than compare `status_code`.

A 429 raises `RateLimitError`, with the wait the server asked for in `retry_after`.
An HTML or other non-JSON error page comes from the CDN or proxy in front of the API rather than the API itself.
Its 4xx raises `GatewayError` and its 5xx raises `ServerError`.
The message names the status and the URL, never the page.
A success whose body is not JSON at all also raises `GatewayError`.
That is usually the web app's page answering a base URL with the wrong path.

`APIError.problem` holds the parsed problem document as a `Problem`, when the API sent one.
A 409 from a batch that committed some items carries the rejected ones on `ConflictError.item_errors`.

A malformed `BOOKSHELF_URL` or `base_url` raises `ConfigurationError`.
So does one carrying a query string, a fragment, a `user@` part or a trailing `/v1`.
A cache directory blocked by a file raises `CacheDirectoryError`, which is also an `OSError`.

## Retries

The client retries a request a few times before it raises, backing off with jitter between attempts.

- A 429 is retried for any method, waiting out `Retry-After` when the server sends one.
  That includes a download from the content CDN.
  A `Retry-After` over 30 seconds raises `RateLimitError` straight away.
- A 502, 503 or 504 is retried for idempotent methods only, so a write is never committed twice.
- A data read (`/data`, timeseries, facets, preview and schema) is never retried after a 5xx or a timeout.
  The read that failed may be the one that took the server down, so a replay would only repeat it.
- A 500 is never retried, because it is the API failing on this request.
- A refused connection is retried for any method, because nothing reached the server.
  A connect timeout is not, since the host did not answer within 10 seconds.
- A read timeout is never retried, since the attempt already waited the whole `timeout`.
  A dropped connection on a metadata read is still retried.

## Reference

::: bookshelf.BookshelfError

::: bookshelf.APIError

::: bookshelf.RequestValidationError

::: bookshelf.AuthenticationError

::: bookshelf.ForbiddenError

::: bookshelf.NotFoundError

::: bookshelf.EntryNotFoundError

::: bookshelf.VersionNotFoundError

::: bookshelf.ConflictError

::: bookshelf.ServerError

::: bookshelf.RateLimitError

::: bookshelf.GatewayError

::: bookshelf.UnexpectedResponseError

::: bookshelf.ContractError

::: bookshelf.OAuthProtocolError

::: bookshelf.TransportError

::: bookshelf.AuthenticationRequiredError

::: bookshelf.AuthConfigurationError

::: bookshelf.ConfigurationError

::: bookshelf.CacheDirectoryError

::: bookshelf.ActionsTokenError

::: bookshelf.OAuthError

::: bookshelf.SelectionError

::: bookshelf.HashMismatchError

::: bookshelf.UnsupportedConversionError

::: bookshelf.DataFrameSupportError

::: bookshelf.PartialRegistrationError

::: bookshelf.InvalidBundleError

::: bookshelf.InvalidRecipeError

::: bookshelf.InvalidReferenceError

::: bookshelf.RecordingError

::: bookshelf.RecordRefusedError

::: bookshelf.Problem

::: bookshelf.ItemError
