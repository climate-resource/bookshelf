# Errors

Failed requests, missing volumes or books, and the errors below all subclass `BookshelfError`,
so catching it covers them.
Looking up an entry a book does not index raises `KeyError` instead.

An HTTP error response raises an `APIError` subclass chosen by status,
so a caller can catch `NotFoundError` or `ConflictError` rather than compare `status_code`.

::: bookshelf.BookshelfError

::: bookshelf.APIError

::: bookshelf.AuthenticationError

::: bookshelf.ForbiddenError

::: bookshelf.NotFoundError

::: bookshelf.ConflictError

::: bookshelf.ServerError

::: bookshelf.UnexpectedResponseError

::: bookshelf.TransportError

::: bookshelf.AuthenticationRequiredError

::: bookshelf.HashMismatchError

::: bookshelf.UnsupportedConversionError
