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

BOOK_DISCOVERY: dict[str, Any] = {
    "license": "CC-BY-4.0",
    "doi": "10.5281/zenodo.1",
    "citation": "Example (2026)",
    "release_url": "https://example.org/releases/v1.0.0",
}


def _patch_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route the commands' client at a mock transport answering each discovery path."""
    routes: dict[str, Any] = {
        "/v1/volumes": {
            **payloads.BOOK_LIST,
            "items": [{**payloads.VOLUME, "discovery": VOLUME_DISCOVERY}],
            "total": 1,
        },
        "/v1/volumes/example": {**payloads.VOLUME_DETAIL, "discovery": VOLUME_DISCOVERY},
        "/v1/books": {
            **payloads.BOOK_LIST,
            "items": [payloads.book_list_item(status="published")],
            "total": 1,
        },
        "/v1/books/b1": {**payloads.BOOK_RESPONSE, "discovery": BOOK_DISCOVERY},
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
