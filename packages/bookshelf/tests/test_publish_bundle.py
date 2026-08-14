"""Tests for ``publish_bundle``, driven against a mock transport rather than a stand-in client."""

from pathlib import Path

import httpx
import pytest

from bookshelf._generated import models
from bookshelf.publisher.bundle import Bundle, BundleBook, InvalidBundleError
from bookshelf.publisher.publish import publish_bundle
from tests._replay import replay_client, replay_response, replayed

POINTER_HASH = "sha256:" + "a" * 64


def _bundle(root: Path, *, data_dictionary: list[dict[str, str]] | None = None) -> Bundle:
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
        name="data",
    )
    bundle.add_book_entry(
        name="data",
        data_dictionary=(
            None
            if data_dictionary is None
            else [models.DataDictionaryEntry.model_validate(entry) for entry in data_dictionary]
        ),
    )
    bundle.mark_book_published()
    bundle.write()
    return bundle


def test_publishing_replays_the_bundle_and_reports_the_edition(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded, response=replay_response(edition=2)) as client:
        outcome = publish_bundle(bundle, client)

    assert outcome.kind == "published"
    assert outcome.edition == 2
    assert outcome.resource_count == 1
    assert outcome.converged is False
    assert [request.url.path for request in recorded] == ["/v1/bundles/replay"]


def test_a_converged_replay_is_a_no_op(tmp_path: Path) -> None:
    """The server settles convergence itself, so a repeated publish mints no rival edition."""
    bundle = _bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []
    answered = replay_response(converged=True, edition=3, dedupe_hits=1)

    with replay_client(recorded, response=answered) as client:
        outcome = publish_bundle(bundle, client)

    assert outcome.kind == "no-op"
    assert outcome.edition == 3
    assert outcome.converged is True
    assert outcome.dedupe_hits == 1


def test_a_dry_run_sends_nothing(tmp_path: Path) -> None:
    """Convergence is the server's to settle, so a dry run has nothing to ask it."""
    bundle = _bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        outcome = publish_bundle(bundle, client, dry_run=True)

    assert outcome.kind == "would-publish"
    assert outcome.edition is None
    assert outcome.resource_count == 1
    assert recorded == []


def test_the_replay_carries_the_recorded_framing(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        publish_bundle(bundle, client)

    book = replayed(recorded)["book"]
    assert book["volume"] == "example"
    assert book["version"] == "v1.0.0"
    assert book["visibility"] == "public"
    assert book["discovery"]["license"] == "MIT"
    assert book["published"] is True


def test_the_entry_carries_the_recorded_data_dictionary(tmp_path: Path) -> None:
    bundle = _bundle(
        tmp_path / "bundle",
        data_dictionary=[{"name": "region", "type": "string", "role": "dimension"}],
    )
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        publish_bundle(bundle, client)

    entry = replayed(recorded)["book"]["entries"][0]
    assert entry["name"] == "data"
    assert [item["name"] for item in entry["data_dictionary"]] == ["region"]
    assert entry["data_dictionary"][0]["role"] == "dimension"


def test_a_bundle_without_book_framing_is_refused(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    bundle.write()
    recorded: list[httpx.Request] = []

    with (
        replay_client(recorded) as client,
        pytest.raises(InvalidBundleError, match="no book framing"),
    ):
        publish_bundle(bundle, client)

    assert recorded == []
