"""Tests for the book metadata each producer path sends.

The platform keeps an edition's metadata when a converging Book leaves it out,
and sets it to empty when the Book sends ``{}``.
So metadata the producer never stated must stay off the wire.
"""

from pathlib import Path

import pytest

from bookshelf._core.ops import build_draft_book
from bookshelf._generated import models
from bookshelf._produce.facade import _draft_request
from bookshelf.publisher.bundle import Bundle, BundleBook
from bookshelf.publisher.replay import _book


def _draft_body(metadata: dict[str, str] | None) -> dict[str, object]:
    request = _draft_request(
        "my-dataset",
        version="v1.0.0",
        description=None,
        license=None,
        visibility=models.Visibility.hidden,
        metadata=metadata,
        bundle_hash=None,
    )
    body = build_draft_book(request).json_body
    assert isinstance(body, dict)
    return body


def test_a_live_draft_that_states_no_metadata_omits_it() -> None:
    assert "metadata" not in _draft_body(None)


@pytest.mark.parametrize("metadata", [{}, {"maturity": "approved"}])
def test_a_live_draft_sends_the_metadata_it_states(metadata: dict[str, str]) -> None:
    assert _draft_body(metadata)["metadata"] == metadata


def test_a_replay_of_a_book_that_states_no_metadata_omits_it() -> None:
    book = _book(BundleBook(volume="example", version="v1.0.0"))

    assert "metadata" not in book.model_dump(mode="json", exclude_unset=True)


@pytest.mark.parametrize("metadata", [{}, {"maturity": "approved"}])
def test_a_replay_sends_the_metadata_the_book_states(metadata: dict[str, str]) -> None:
    book = _book(BundleBook(volume="example", version="v1.0.0", metadata=metadata))

    assert book.model_dump(mode="json", exclude_unset=True)["metadata"] == metadata


@pytest.mark.parametrize(("version", "expected"), [("3.11", None), ("3.12", {})])
def test_only_an_older_manifest_reads_empty_metadata_as_unstated(
    tmp_path: Path, version: str, expected: dict[str, str] | None
) -> None:
    """A minor older than 3.12 wrote ``{}`` whether or not the build stated any metadata."""
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "manifest.lock").write_text(
        f"schema_version: '{version}'\n"
        "book:\n  volume: example\n  version: v1.0.0\n  metadata: {}\n"
        "resources: []\n"
    )

    book = Bundle.read(root).manifest.book

    assert book is not None
    assert book.metadata == expected
