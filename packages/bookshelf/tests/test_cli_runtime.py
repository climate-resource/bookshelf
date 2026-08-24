"""The CLI exit-code table, asserted over the full SDK error hierarchy."""

import pytest
import typer

from bookshelf._cli._runtime import command_errors
from bookshelf._core import errors


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (errors.AuthenticationError("no", status_code=401), 3),
        (errors.ForbiddenError("not yours", status_code=403), 4),
        (errors.NotFoundError("gone", status_code=404), 5),
        (errors.ValidationError("bad", status_code=422), 2),
        (errors.ServerError("boom", status_code=502), 6),
        (errors.TransportError("refused"), 6),
        (errors.ConflictError("clash", status_code=409), 1),
        (errors.UnexpectedResponseError("odd", status_code=418), 1),
    ],
)
def test_exit_code_table(exc: errors.BookshelfError, expected: int) -> None:
    with pytest.raises(typer.Exit) as excinfo, command_errors():
        raise exc
    assert excinfo.value.exit_code == expected
