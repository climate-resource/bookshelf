"""Tests for ``publish_bundle``, driven against a mock transport rather than a stand-in client."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from bookshelf._generated import models
from bookshelf.facade import Bookshelf
from bookshelf.publisher.bundle import Bundle, BundleBook, compute_book_bundle_hash
from bookshelf.publisher.publish import publish_bundle
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"
POINTER_HASH = "sha256:" + "a" * 64


def _bundle(
    root: Path, *, tracking_id: UUID, data_dictionary: list[dict[str, str]] | None = None
) -> Bundle:
    """Write a replayable published book bundle carrying one external pointer."""
    bundle = Bundle(root)
    bundle.set_book(
        BundleBook(
            volume="example",
            version="v1.0.0",
            visibility="public",
            license="MIT",
        )
    )
    bundle.add_pointer(
        external_uri="https://example.test/data.csv",
        hash_=POINTER_HASH,
        type_="document",
        tracking_id=tracking_id,
    )
    bundle.add_book_entry(
        name_in_book="data",
        tracking_id=tracking_id,
        data_dictionary=(
            None
            if data_dictionary is None
            else [models.DataDictionaryEntry.model_validate(entry) for entry in data_dictionary]
        ),
    )
    bundle.mark_book_published()
    bundle.write()
    return bundle


def _book_detail(*, status: str, edition: int) -> dict[str, Any]:
    return {**payloads.BOOK_DETAIL, "status": status, "edition": edition}


def _client(recorded: list[httpx.Request], *, status: str = "draft", edition: int = 1) -> Bookshelf:
    """Answer the four routes a publish walks, recording what it sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        path = request.url.path
        if path == "/v1/books":
            return httpx.Response(201, json=_book_detail(status=status, edition=edition))
        if path == "/v1/resources/registrations":
            return httpx.Response(
                200,
                json={
                    "activity_created": False,
                    "atomic": True,
                    "registered": [
                        {
                            "index": 0,
                            "status": "created",
                            "outcome": {
                                "status": "created",
                                "tracking_id": str(uuid4()),
                            },
                        }
                    ],
                },
            )
        if path.endswith("/entries"):
            return httpx.Response(201, json=payloads.ENTRY_ATTACHED)
        if path.endswith("/publish"):
            return httpx.Response(200, json=_book_detail(status="published", edition=edition))
        raise AssertionError(f"unexpected request to {path}")

    return Bookshelf(BASE_URL, auth=None, transport=httpx.MockTransport(handler))


def _drafts(recorded: list[httpx.Request]) -> list[httpx.Request]:
    return [
        request
        for request in recorded
        if request.method == "POST" and request.url.path == "/v1/books"
    ]


def _attachments(recorded: list[httpx.Request]) -> list[httpx.Request]:
    return [request for request in recorded if request.url.path.endswith("/entries")]


def test_publishing_replays_the_bundle_and_reports_the_edition(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle", tracking_id=uuid4())
    recorded: list[httpx.Request] = []

    with _client(recorded, status="draft", edition=2) as client:
        outcome = publish_bundle(bundle, client)

    assert outcome.kind == "published"
    assert outcome.edition == 2
    assert outcome.resources == 1
    assert [request.url.path for request in recorded][-1].endswith("/publish")


def test_publishing_drafts_once(tmp_path: Path) -> None:
    """The draft that decides the outcome is the draft the replay resumes."""
    bundle = _bundle(tmp_path / "bundle", tracking_id=uuid4())
    recorded: list[httpx.Request] = []

    with _client(recorded) as client:
        publish_bundle(bundle, client)

    assert len(_drafts(recorded)) == 1


def test_an_existing_published_edition_is_a_no_op(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle", tracking_id=uuid4())
    recorded: list[httpx.Request] = []

    with _client(recorded, status="published", edition=3) as client:
        outcome = publish_bundle(bundle, client)

    assert outcome.kind == "no-op"
    assert outcome.edition == 3
    assert outcome.resources == 0
    assert len(recorded) == 1, "a no-op writes nothing beyond the draft that reveals it"


@pytest.mark.parametrize("status", ["draft", "published"])
def test_a_dry_run_writes_nothing_beyond_the_draft(status: str, tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle", tracking_id=uuid4())
    recorded: list[httpx.Request] = []

    with _client(recorded, status=status, edition=4) as client:
        outcome = publish_bundle(bundle, client, dry_run=True)

    assert outcome.kind == ("no-op" if status == "published" else "would-publish")
    assert outcome.edition == 4
    assert len(recorded) == 1


def test_the_draft_carries_the_recorded_framing_and_the_bundle_hash(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle", tracking_id=uuid4())
    recorded: list[httpx.Request] = []

    with _client(recorded) as client:
        outcome = publish_bundle(bundle, client, dry_run=True)

    body = json.loads(_drafts(recorded)[0].content)
    assert body["series_name"] == "example"
    assert body["version"] == "v1.0.0"
    assert body["visibility"] == "public"
    assert body["license"] == "MIT"
    assert body["bundle_hash"] == outcome.bundle_hash
    assert outcome.bundle_hash == compute_book_bundle_hash(bundle.manifest)


def test_the_attachment_carries_the_recorded_data_dictionary(tmp_path: Path) -> None:
    bundle = _bundle(
        tmp_path / "bundle",
        tracking_id=uuid4(),
        data_dictionary=[{"name": "region", "type": "string", "role": "dimension"}],
    )
    recorded: list[httpx.Request] = []

    with _client(recorded) as client:
        publish_bundle(bundle, client)

    draft_body = json.loads(_drafts(recorded)[0].content)
    assert "data_dictionary" not in draft_body
    sent = json.loads(_attachments(recorded)[0].content)["data_dictionary"]
    assert [entry["name"] for entry in sent] == ["region"]
    assert sent[0]["role"] == "dimension"


def test_a_bundle_without_book_framing_is_refused(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    bundle.write()
    recorded: list[httpx.Request] = []

    with _client(recorded) as client, pytest.raises(ValueError, match="no book framing"):
        publish_bundle(bundle, client)

    assert recorded == []
