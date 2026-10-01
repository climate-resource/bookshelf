"""Tests for what ``bookshelf search`` and ``bookshelf show`` print from discovery."""

import json
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._core.client import BookshelfClient
from tests import _core_payloads as payloads

API_URL = "https://bookshelf.test"
runner = CliRunner()

VOLUME_DISCOVERY: dict[str, Any] = {
    "title": "Example",
    "license": "CC-BY-4.0",
    "publisher": "Climate Resource",
    "topics": ["emissions"],
    "keywords": ["ghg"],
}

RESOURCE: dict[str, Any] = {
    "id": "0197a000-0000-7000-8000-0000000000a1",
    "tracking_id": "0197a000-0000-7000-8000-0000000000c1",
    "name": "by_country",
    "type": "timeseries",
    "visibility": "public",
    "format": "parquet",
    "size_bytes": 10,
    "hash": "sha256:" + "ab" * 32,
    "content_hash": None,
}

BOOK_DISCOVERY: dict[str, Any] = {
    "license": "CC-BY-4.0",
    "doi": "10.5281/zenodo.1",
    "citation": "Example (2026)",
    "release_url": "https://example.org/releases/v1.0.0",
}


def _patch_client(monkeypatch: pytest.MonkeyPatch, *, volume_total: int = 1) -> None:
    """Route the commands' client at a mock transport answering each discovery path."""
    routes: dict[str, Any] = {
        "/v1/volumes": {
            **payloads.BOOK_LIST,
            "items": [{**payloads.VOLUME, "discovery": VOLUME_DISCOVERY}],
            "total": volume_total,
            "has_more": volume_total > 1,
        },
        "/v1/volumes/example": {**payloads.VOLUME_DETAIL, "discovery": VOLUME_DISCOVERY},
        "/v1/books": {
            **payloads.BOOK_LIST,
            "items": [payloads.book_list_item(status="published")],
            "total": 1,
        },
        "/v1/books/b1": {
            **payloads.BOOK_RESPONSE,
            "discovery": BOOK_DISCOVERY,
            "resources": [RESOURCE, {**RESOURCE, "name": "by_region"}],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=routes[request.url.path])

    monkeypatch.setattr(
        "bookshelf._cli.discovery.BookshelfClient",
        lambda url: BookshelfClient(url, auth=None, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setenv("BOOKSHELF_URL", API_URL)


def _run_json(monkeypatch: pytest.MonkeyPatch, *args: str) -> dict[str, Any]:
    """Run a command with ``--json`` and return its first document, one per line."""
    _patch_client(monkeypatch)
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    document: dict[str, Any] = json.loads(result.stdout.splitlines()[0])
    return document


def test_search_prints_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _run_json(monkeypatch, "search")

    assert row["keywords"] == ["ghg"]


def test_search_labels_the_licence_as_the_latest_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _run_json(monkeypatch, "search")

    assert row["latest_license"] == "CC-BY-4.0"
    assert "license" not in row


def test_show_volume_prints_keywords_and_latest_release_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _run_json(monkeypatch, "show", "example")

    assert document["keywords"] == ["ghg"]
    assert document["latest_license"] == "CC-BY-4.0"
    assert document["latest_publisher"] == "Climate Resource"
    assert "license" not in document
    assert "publisher" not in document


def test_show_book_prints_its_own_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _run_json(monkeypatch, "show", "example@v1.0.0")

    assert {key: document[key] for key in BOOK_DISCOVERY} == BOOK_DISCOVERY


def test_show_entry_reports_the_tracking_id_and_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _run_json(monkeypatch, "show", "example@v1.0.0/by_country")

    assert document["tracking_id"] == RESOURCE["tracking_id"]
    assert document["content_hash"] == RESOURCE["hash"]


def test_show_book_reports_each_resource_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _run_json(monkeypatch, "show", "example@v1.0.0")

    assert {resource["content_hash"] for resource in document["resources"]} == {RESOURCE["hash"]}


def test_show_book_separates_each_resource_block(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch)

    result = runner.invoke(app, ["show", "example@v1.0.0"])

    assert result.exit_code == 0, result.output
    resources = result.stdout.split("Resources\n", 1)[1]
    assert "\n\n  Name" in resources


def test_search_says_when_results_are_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, volume_total=26)

    result = runner.invoke(app, ["search", "--json"])

    assert result.exit_code == 0, result.output
    assert "1 of 26" in result.stderr
    assert "--offset 1" in result.stderr


def test_search_facets_refuses_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch)

    result = runner.invoke(app, ["search", "--facets", "--topic", "emissions"])

    assert result.exit_code == 2
    assert "--facets" in result.stderr


def test_search_facets_spell_licenses_like_the_volume_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bookshelf._cli.discovery.BookshelfClient",
        lambda url: BookshelfClient(
            url,
            auth=None,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"licenses": ["CC-BY-4.0"]})
            ),
        ),
    )
    monkeypatch.setenv("BOOKSHELF_URL", API_URL)

    result = runner.invoke(app, ["search", "--facets", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["licenses"] == ["CC-BY-4.0"]


def test_search_accepts_the_license_spelling(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _run_json(monkeypatch, "search", "--license", "CC-BY-4.0")

    assert row["name"] == payloads.VOLUME["name"]


def test_a_free_text_miss_does_not_point_at_facets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bookshelf._cli.discovery.BookshelfClient",
        lambda url: BookshelfClient(
            url,
            auth=None,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json=payloads.BOOK_LIST)
            ),
        ),
    )
    monkeypatch.setenv("BOOKSHELF_URL", API_URL)

    result = runner.invoke(app, ["search", "nothing-like-this"])

    assert result.exit_code == 0, result.output
    assert "--facets" not in result.stderr
