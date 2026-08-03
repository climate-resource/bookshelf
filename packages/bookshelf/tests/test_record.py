"""Tests for the bundle-backed producer recording adapter."""

from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from bookshelf._core.client import BookshelfClient
from bookshelf._produce.types import RegisterItem
from bookshelf.cache import ContentCache
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.record import RecordingActivity


def _activity(bundle: Bundle, cache_path: Path) -> RecordingActivity:
    return RecordingActivity(
        bundle,
        Mock(spec=BookshelfClient),
        ContentCache(cache_path),
        activity_id=uuid4(),
        kind="run",
        code_ref="test",
        config={},
        runner_name="pytest",
    )


def test_atomic_register_many_commits_the_complete_batch(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")

    with _activity(bundle, tmp_path / "cache") as activity:
        resources = activity.register_many(
            [
                RegisterItem(b"first", type="document"),
                RegisterItem(b"second", type="document"),
            ],
            atomic=True,
        )

    assert [resource.tracking_id for resource in resources] == [
        resource.tracking_id for resource in bundle.manifest.resources
    ]
    assert [bundle.resource_bytes(resource) for resource in bundle.manifest.resources] == [
        b"first",
        b"second",
    ]


def test_atomic_register_many_does_not_record_a_partial_batch(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    activity = _activity(bundle, tmp_path / "cache")

    with activity, pytest.raises(TypeError, match="Cannot serialise"):
        activity.register_many(
            [
                RegisterItem(b"first", type="document"),
                RegisterItem(object(), type="document"),
            ],
            atomic=True,
        )

    assert bundle.manifest.activity is None
    assert bundle.manifest.resources == []
    assert not bundle.resources_dir.exists()


def test_a_later_batch_does_not_rewrite_earlier_lineage(tmp_path: Path) -> None:
    """A recorded input belongs to the resource that consumed it.

    Recording the notebook documents happens after the build has registered its
    outputs, so a batch that back-filled its merged inputs across the whole
    manifest would hand the raw input to every resource, including itself.
    """
    bundle = Bundle(tmp_path / "bundle")

    with _activity(bundle, tmp_path / "cache") as activity:
        raw = activity.register(b"raw", type="tabular")
        activity.register(b"derived", type="tabular", used=[raw.tracking_id])
        activity.register_many([RegisterItem(b"notebook", type="document")])

    recorded = {
        resource.tracking_id: [reference.tracking_id for reference in resource.used]
        for resource in bundle.manifest.resources
    }
    raw_used, derived_used, document_used = recorded.values()

    assert raw_used == [], "the raw input consumed nothing and must not cite itself"
    assert derived_used == [raw.tracking_id]
    assert document_used == [raw.tracking_id]
