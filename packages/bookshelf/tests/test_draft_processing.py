"""Tests for the processing fingerprint a draft request carries.

These assert on the bytes the request would send rather than on the model,
because the defect they guard against lived between the two.
``processing`` is a plain array in the contract, not a nullable one,
so a draft that states nothing must leave the key off rather than send a null.
The client dumps with ``exclude_unset``, which makes an unconditionally passed
``None`` reach the wire, and that is a 422 for every caller who never mentioned it.
"""

from bookshelf._core.ops import build_draft_book
from bookshelf._generated import models
from bookshelf._produce.facade import _draft_request

FRAMING = {
    "version": "v1.0.0",
    "description": None,
    "license": None,
    "visibility": models.Visibility.hidden,
    "metadata": None,
    "bundle_hash": None,
}


def _sent(processing: object = "unstated") -> dict[str, object]:
    """Return the JSON body a draft request would put on the wire."""
    extra = {} if processing == "unstated" else {"processing": processing}
    request = _draft_request("my-dataset", **FRAMING, **extra)  # type: ignore[arg-type]
    body = build_draft_book(request).json_body
    assert isinstance(body, dict)
    return body


def test_a_draft_that_states_no_processing_omits_the_field() -> None:
    """The field is a plain array, so a null would be refused. Saying nothing sends nothing."""
    assert "processing" not in _sent()


def test_a_draft_with_no_generating_activity_sends_an_empty_list() -> None:
    """``[]`` is a book no activity generated, which the contract distinguishes from silence."""
    assert _sent(()) == {**_sent(), "processing": []}


def test_a_draft_with_two_activities_sends_both_pairs() -> None:
    """The platform deduplicates and sorts, so both pairs travel in the order given."""
    pairs = [("repo@one", "sha256:aaa"), ("repo@two", "sha256:bbb")]

    assert _sent(pairs)["processing"] == [
        ["repo@one", "sha256:aaa"],
        ["repo@two", "sha256:bbb"],
    ]
