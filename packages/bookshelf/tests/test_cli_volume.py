"""Tests for ``bookshelf volume create``, ``update`` and ``delete``."""

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._cli._runtime import EXIT_FORBIDDEN, EXIT_OK, EXIT_USAGE
from bookshelf.facade import Bookshelf
from tests import _core_payloads as payloads

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
API_URL = "https://bookshelf.test"
runner = CliRunner()


def _plain(text: str) -> str:
    """Strip ANSI styling, which typer emits for its own usage errors under CI."""
    return _ANSI.sub("", text)


def _patch_client(
    monkeypatch: pytest.MonkeyPatch, status: int, payload: Any = None
) -> list[httpx.Request]:
    """Route the command's facade at a mock transport, returning what it sent."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(
        "bookshelf._cli.volume.Bookshelf",
        lambda url: Bookshelf(url, auth=None, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setenv("BOOKSHELF_URL", API_URL)
    return recorded


def test_volume_create_posts_the_named_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _patch_client(monkeypatch, 201, payloads.VOLUME)

    result = runner.invoke(
        app,
        [
            "volume",
            "create",
            "example",
            "--licence",
            "MIT",
            "--description",
            "Country emissions",
            "--author",
            "A Person",
            "--json",
        ],
    )

    assert result.exit_code == EXIT_OK
    assert json.loads(result.stdout)["name"] == "example"
    assert (recorded[0].method, recorded[0].url.path) == ("POST", "/v1/volumes")
    assert json.loads(recorded[0].content) == {
        "name": "example",
        "license": "MIT",
        "description": "Country emissions",
        "authors": [{"name": "A Person"}],
    }


def test_volume_create_human_output_names_the_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, 201, payloads.VOLUME)

    result = runner.invoke(app, ["volume", "create", "example", "--licence", "MIT"])

    assert result.exit_code == EXIT_OK
    assert "example" in result.stdout
    assert "Licence" in result.stdout


def test_volume_create_requires_a_licence(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, 201, payloads.VOLUME)

    result = runner.invoke(app, ["volume", "create", "example"])

    assert result.exit_code == EXIT_USAGE
    assert "--licence" in _plain(result.stderr)


def test_volume_create_reads_a_metadata_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = _patch_client(monkeypatch, 201, payloads.VOLUME)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"source": "upstream"}))

    result = runner.invoke(
        app,
        ["volume", "create", "example", "--licence", "MIT", "--metadata", str(metadata), "--json"],
    )

    assert result.exit_code == EXIT_OK
    assert json.loads(recorded[0].content)["metadata"] == {"source": "upstream"}


def test_volume_create_rejects_metadata_that_is_not_an_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = _patch_client(monkeypatch, 201, payloads.VOLUME)
    metadata = tmp_path / "metadata.json"
    metadata.write_text("[1, 2]")

    result = runner.invoke(
        app, ["volume", "create", "example", "--licence", "MIT", "--metadata", str(metadata)]
    )

    assert result.exit_code == EXIT_USAGE
    assert "not a JSON object" in _plain(result.stderr)
    assert recorded == []


def test_volume_create_rejects_unreadable_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = _patch_client(monkeypatch, 201, payloads.VOLUME)

    result = runner.invoke(
        app,
        [
            "volume",
            "create",
            "example",
            "--licence",
            "MIT",
            "--metadata",
            str(tmp_path / "absent.json"),
        ],
    )

    assert result.exit_code == EXIT_USAGE
    assert "cannot read the metadata" in _plain(result.stderr)
    assert recorded == []


def test_volume_update_patches_only_what_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _patch_client(monkeypatch, 200, payloads.VOLUME)

    result = runner.invoke(app, ["volume", "update", "example", "--citation", "Cite me", "--json"])

    assert result.exit_code == EXIT_OK
    assert (recorded[0].method, recorded[0].url.path) == ("PATCH", "/v1/volumes/example")
    assert json.loads(recorded[0].content) == {"citation": "Cite me"}


def test_volume_update_refuses_an_empty_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _patch_client(monkeypatch, 200, payloads.VOLUME)

    result = runner.invoke(app, ["volume", "update", "example"])

    assert result.exit_code == EXIT_USAGE
    assert "at least one field" in _plain(result.stderr)
    assert recorded == []


def test_volume_delete_needs_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _patch_client(monkeypatch, 204)

    result = runner.invoke(app, ["volume", "delete", "example"])

    assert result.exit_code == EXIT_USAGE
    assert "--yes" in _plain(result.stderr)
    assert recorded == []


def test_volume_delete_reports_the_deletion(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _patch_client(monkeypatch, 204)

    result = runner.invoke(app, ["volume", "delete", "example", "--yes", "--json"])

    assert result.exit_code == EXIT_OK
    assert json.loads(result.stdout) == {"outcome": "deleted", "volume": "example"}
    assert (recorded[0].method, recorded[0].url.path) == ("DELETE", "/v1/volumes/example")


def test_volume_delete_maps_the_admin_refusal_to_its_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creation needs WRITE and deletion needs ADMIN, so this is a routine outcome to report."""
    problem = dict(payloads.PROBLEM_CONFLICT, status=403, detail="admin permission required")
    _patch_client(monkeypatch, 403, problem)

    result = runner.invoke(app, ["volume", "delete", "example", "--yes"])

    assert result.exit_code == EXIT_FORBIDDEN
    assert "admin permission required" in _plain(result.stderr)
