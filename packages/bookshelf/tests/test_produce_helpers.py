"""Tests for the shared registration-outcome helpers (``bookshelf._produce.helpers``)."""

from uuid import UUID

import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.helpers import paired_successes, single_success, used_ref
from bookshelf._produce.types import RegisterItem, RegistrationSuccess, Used


def _item(name: str, resource_type: str) -> models.RegisterResourceItem:
    return models.RegisterResourceItem(
        tracking_id=None,
        type=models.ResourceType(resource_type),
        name=name,
    )


def _outcome(suffix: str) -> models.RegistrationOutcome:
    return models.RegistrationOutcome(
        tracking_id=UUID(f"0197a000-0000-7000-8000-0000000000{suffix}"),
        status=models.Status2.created,
    )


def test_paired_successes_follows_the_server_reported_index() -> None:
    """A reordered response must still resolve each outcome to its own request item."""
    items = [_item("first", "tabular"), _item("second", "document")]
    successful = [
        RegistrationSuccess(index=1, outcome=_outcome("b2")),
        RegistrationSuccess(index=0, outcome=_outcome("b1")),
    ]
    paired = paired_successes(successful, items)
    assert [
        (outcome.tracking_id, item.name.root if item.name else None) for outcome, item in paired
    ] == [
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
    assert [item.name.root for _outcome_, item in paired if item.name] == ["first", "second"]


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


def test_used_ref_sends_a_name_the_request_resolves_locally() -> None:
    """The wire field is ``resource_name``, and it resolves inside this request only."""
    reference = used_ref(Used(name="upstream-emissions"))

    assert isinstance(reference, models.UsedRefByResourceName)
    assert reference.resource_name == "upstream-emissions"


@pytest.mark.parametrize(
    "name",
    ["upstream/emissions", "Upstream", "-leading", "", "a" * 201],
)
def test_a_name_outside_the_platform_charset_is_refused(name: str) -> None:
    """A name the platform would reject fails at the call site, not as a 422."""
    with pytest.raises(ValueError):
        Used(name=name)
    with pytest.raises(ValueError):
        RegisterItem(obj=object(), type="tabular", name=name)
