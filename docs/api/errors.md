# Errors

Failed requests, missing volumes or books, and the errors below all subclass `BookshelfError`,
so catching it covers them.
Looking up an entry a book does not index raises `KeyError` instead.

::: bookshelf.BookshelfError

::: bookshelf.HashMismatchError

::: bookshelf.UnsupportedConversionError
