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
