"""Tests for resolving recorded lineage against what a replay actually registered."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from bookshelf.publisher.bundle import BundleResource, BundleUsedRef
from bookshelf.publisher.replay import _resource_used


def _resource(tracking_id, used=()):
    return BundleResource(
        tracking_id=tracking_id,
        type="tabular",
        hash="sha256:" + "0" * 64,
        used=[BundleUsedRef(tracking_id=reference) for reference in used],
    )


def test_an_input_is_cited_by_the_id_the_server_returned():
    """Dedupe answers a registration with the resource the deployment already holds.

    The recorded id then names nothing, so citing it verbatim breaks the lineage of
    everything downstream.
    """
    recorded_raw, existing_raw, derived = uuid4(), uuid4(), uuid4()
    registered = {recorded_raw: SimpleNamespace(tracking_id=existing_raw)}

    used = _resource_used(_resource(derived, used=[recorded_raw]), registered, frozenset())

    assert used == [existing_raw]


def test_a_resource_never_cites_itself():
    """A bundle recorded before inputs were kept per resource carries the whole set
    on each of them, so the first output names itself."""
    raw = uuid4()

    used = _resource_used(_resource(raw, used=[raw]), {}, frozenset({raw}))

    assert used == []


def test_an_id_from_outside_the_bundle_passes_through():
    """A replay resolves only what it registered. Anything else is the server's to find."""
    outside, derived = uuid4(), uuid4()

    used = _resource_used(_resource(derived, used=[outside]), {}, frozenset({derived}))

    assert used == [outside]


def test_an_input_the_bundle_records_later_is_refused():
    """Passing it through would send an id the server may never have minted,
    which is the failure this resolution exists to prevent."""
    later, derived = uuid4(), uuid4()

    with pytest.raises(ValueError, match="records after it"):
        _resource_used(_resource(derived, used=[later]), {}, frozenset({derived, later}))


def test_repeated_inputs_are_cited_once():
    """Two recorded ids can converge on one resource after dedupe."""
    first, second, existing, derived = uuid4(), uuid4(), uuid4(), uuid4()
    registered = {
        first: SimpleNamespace(tracking_id=existing),
        second: SimpleNamespace(tracking_id=existing),
    }

    used = _resource_used(_resource(derived, used=[first, second]), registered, frozenset())

    assert used == [existing]
