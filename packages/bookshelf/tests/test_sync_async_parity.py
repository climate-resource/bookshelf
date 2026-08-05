"""Assert the sync and async surfaces expose the same shape.

This is a signature-level check, and only that.
It compares parameter names, order, kinds, annotations and defaults,
plus the return annotation once the ``Async`` prefix is normalised away.
It says nothing about what the bodies do,
so it would not have caught a difference like one twin moving a hash off the event loop
while the other does not.
It catches drift in the shape of the API, not drift in behaviour.

The client's operation methods are generated,
so they cannot drift and are not covered here.
These facades are hand-written twins that generation will never reach,
which is exactly why they need a guard.
"""

import inspect
import re
from typing import Any

import pytest

from bookshelf import facade
from bookshelf._consume import resources
from bookshelf._produce import facade as produce

CLASS_PAIRS = [
    (facade.Bookshelf, facade.AsyncBookshelf),
    (produce.LiveSink, produce.AsyncLiveSink),
    (resources.Resource, resources.AsyncResource),
    (resources.BookEntry, resources.AsyncBookEntry),
]

# Pre-existing asymmetries, recorded rather than fixed.
# Each key is (sync class name, member name).
KNOWN_EXCEPTIONS = {
    # The async surface follows the aclose() convention instead.
    ("Bookshelf", "close"),
    # AsyncResource offers _get_metadata() and _get_type() coroutines,
    # because a property cannot be awaited.
    ("Resource", "metadata"),
    ("Resource", "type"),
}

_ASYNC_PREFIX = re.compile(r"\bAsync(?=[A-Z])")


def _public_members(cls: type) -> dict[str, Any]:
    return {name: value for name, value in vars(cls).items() if not name.startswith("_")}


def _twin(async_members: dict[str, Any], name: str) -> Any:
    return async_members.get(name, async_members.get(f"{name}_async"))


def _cases() -> list[tuple[type, type, str, Any]]:
    return [
        (sync_cls, async_cls, name, value)
        for sync_cls, async_cls in CLASS_PAIRS
        for name, value in sorted(_public_members(sync_cls).items())
        if callable(value) or isinstance(value, property)
    ]


@pytest.mark.parametrize(
    ("sync_cls", "async_cls", "name", "member"),
    _cases(),
    ids=lambda value: value.__name__ if isinstance(value, type) else None,
)
def test_async_twin_matches(sync_cls: type, async_cls: type, name: str, member: Any) -> None:
    twin = _twin(_public_members(async_cls), name)
    if (sync_cls.__name__, name) in KNOWN_EXCEPTIONS:
        pytest.skip(f"{sync_cls.__name__}.{name} is a recorded pre-existing asymmetry")
    assert twin is not None, f"{async_cls.__name__} has no twin for {sync_cls.__name__}.{name}"

    assert isinstance(member, property) == isinstance(twin, property), (
        f"{sync_cls.__name__}.{name} and its twin disagree on being a property"
    )
    if isinstance(member, property):
        return

    expected = inspect.signature(member)
    actual = inspect.signature(twin)
    assert list(expected.parameters.values()) == list(actual.parameters.values()), (
        f"{sync_cls.__name__}.{name} and its twin have different parameters"
    )
    assert _ASYNC_PREFIX.sub("", str(actual.return_annotation)) == str(
        expected.return_annotation
    ), f"{sync_cls.__name__}.{name} and its twin have different return types"


def test_every_class_pair_has_cases() -> None:
    """Guard the parametrisation itself, so a rename cannot quietly empty the suite."""
    covered = {sync_cls for sync_cls, _, _, _ in _cases()}
    assert covered == {sync_cls for sync_cls, _ in CLASS_PAIRS}
