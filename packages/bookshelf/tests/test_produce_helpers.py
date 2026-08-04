"""Tests for the shared registration-outcome helpers (``bookshelf._produce.helpers``)."""

from uuid import UUID

import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.helpers import paired_successes, single_success
from bookshelf._produce.types import RegistrationSuccess


def _item(logical_key: str, resource_type: str) -> models.RegisterResourceItem:
    return models.RegisterResourceItem(
        tracking_id=None,
        type=models.ResourceType(resource_type),
        logical_key=logical_key,
    )


def _outcome(suffix: str) -> models.RegistrationOutcome:
    return models.RegistrationOutcome(
        tracking_id=UUID(f"0197a000-0000-7000-8000-0000000000{suffix}"),
        status=models.Status1.created,
    )


def test_paired_successes_follows_the_server_reported_index() -> None:
    """A reordered response must still resolve each outcome to its own request item."""
    items = [_item("first", "tabular"), _item("second", "document")]
    successful = [
        RegistrationSuccess(index=1, outcome=_outcome("b2")),
        RegistrationSuccess(index=0, outcome=_outcome("b1")),
    ]
    paired = paired_successes(successful, items)
    assert [(outcome.tracking_id, item.logical_key) for outcome, item in paired] == [
        (UUID("0197a000-0000-7000-8000-0000000000b2"), "second"),
        (UUID("0197a000-0000-7000-8000-0000000000b1"), "first"),
    ]


def test_paired_successes_falls_back_to_position_without_an_index() -> None:
    items = [_item("first", "tabular"), _item("second", "document")]
    successful = [
        RegistrationSuccess(index=-1, outcome=_outcome("b1")),
        RegistrationSuccess(index=-1, outcome=_outcome("b2")),
    ]
    paired = paired_successes(successful, items)
    assert [item.logical_key for _outcome_, item in paired] == ["first", "second"]


def test_paired_successes_refuses_a_short_response() -> None:
    """A short batch response raises a typed SDK error, not a bare ValueError."""
    items = [_item("first", "tabular"), _item("second", "document")]
    successful = [RegistrationSuccess(index=0, outcome=_outcome("b1"))]
    with pytest.raises(BookshelfError):
        paired_successes(successful, items)


def test_single_success_refuses_a_response_that_registered_nothing() -> None:
    with pytest.raises(BookshelfError):
        single_success([])


def test_single_success_returns_the_only_outcome() -> None:
    outcome = _outcome("b9")
    assert single_success([RegistrationSuccess(index=0, outcome=outcome)]) is outcome
