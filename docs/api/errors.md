# Errors

Every error the SDK raises for a failed operation subclasses `BookshelfError`.
Each class below is importable from `bookshelf`.

Misusing the API raises Python's own `TypeError` or `ValueError` instead,
for example passing an argument a resource type does not accept.
These signal a bug in the calling code rather than a condition to handle.

## Not found

A volume, version, book, entry or resource that does not exist raises `NotFoundError`,
whether the platform answered 404 or the SDK settled the lookup locally.
`NotFoundError` is also a `LookupError`.

Looking up an entry a book does not index raises `EntryNotFoundError`.
It is also a `KeyError`, so `book["name"]` behaves like any other mapping.

Filtering on a column the data does not have raises `SelectionError`,
which is also a `KeyError`.

## HTTP responses

An HTTP error response raises an `APIError` subclass chosen by status,
so a caller can catch `NotFoundError` or `ConflictError` rather than compare `status_code`.

## Reference

::: bookshelf.BookshelfError

::: bookshelf.APIError

::: bookshelf.ValidationError

::: bookshelf.AuthenticationError

::: bookshelf.ForbiddenError

::: bookshelf.NotFoundError

::: bookshelf.EntryNotFoundError

::: bookshelf.ConflictError

::: bookshelf.ServerError

::: bookshelf.UnexpectedResponseError

::: bookshelf.OAuthProtocolError

::: bookshelf.TransportError

::: bookshelf.AuthenticationRequiredError

::: bookshelf.AuthConfigurationError

::: bookshelf.ActionsTokenError

::: bookshelf.OAuthError

::: bookshelf.SelectionError

::: bookshelf.HashMismatchError

::: bookshelf.UnsupportedConversionError

::: bookshelf.DataFrameSupportError

::: bookshelf.PartialRegistrationError

::: bookshelf.InvalidBundleError
