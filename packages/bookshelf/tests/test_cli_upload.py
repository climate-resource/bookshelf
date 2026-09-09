"""Tests for ``bookshelf upload``."""

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._cli._runtime import EXIT_AUTH_REQUIRED, EXIT_OK, EXIT_USAGE
from bookshelf.facade import Bookshelf
from tests import _core_payloads as payloads

API_URL = "https://bookshelf.test"
TRACKING_ID = "0197a000-0000-7000-8000-000000000001"
runner = CliRunner()


def _registered(status: str) -> dict[str, Any]:
    return {
        "activity_created": False,
        "atomic": True,
        "registered": [
            {
                "index": 0,
                "status": status,
                "outcome": {"status": status, "tracking_id": TRACKING_ID, "dedupe": True},
            }
        ],
    }


def _patch_client(
    monkeypatch: pytest.MonkeyPatch, *, outcome: str = "created", status: int = 200
) -> list[httpx.Request]:
    """Route the command's facade at a mock transport, returning what it sent."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if status != 200:
            return httpx.Response(status, json=payloads.problem(status, "Unauthorized", "no token"))
        if request.url.path == "/v1/resources/uploads":
            return httpx.Response(200, json=payloads.UPLOAD_EXISTS)
        if request.method == "GET":
            return httpx.Response(200, json=payloads.RESOURCE_READ)
        return httpx.Response(200, json=_registered(outcome))

    monkeypatch.setattr(
        "bookshelf._cli.uploads.Bookshelf",
        lambda url: Bookshelf(url, auth=None, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setenv("BOOKSHELF_URL", API_URL)
    return recorded


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    path = tmp_path / "Scenario Compass.xlsx"
    path.write_bytes(b"not really a workbook")
    return path


def test_upload_prints_the_uri_first(monkeypatch: pytest.MonkeyPatch, workbook: Path) -> None:
    recorded = _patch_client(monkeypatch)
    digest = hashlib.sha256(workbook.read_bytes()).hexdigest()

    result = runner.invoke(app, ["upload", str(workbook), "--type", "binary"])

    assert result.exit_code == EXIT_OK, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == f"bookshelf://sha256/{digest}"
    assert lines[1].split() == ["Tracking", "id", TRACKING_ID]
    assert "created" in result.stdout
    assert [request.url.path for request in recorded] == [
        "/v1/resources/uploads",
        "/v1/resources/registrations",
    ]
    item = json.loads(recorded[1].content)["items"][0]
    assert item["name"] == "scenario-compass.xlsx"
    assert item["type"] == "binary"
    assert item["visibility"] == "hidden"
    assert item["hash"] == f"sha256:{digest}"


def test_upload_json_carries_the_uri_and_the_identity(
    monkeypatch: pytest.MonkeyPatch, workbook: Path
) -> None:
    _patch_client(monkeypatch)
    digest = hashlib.sha256(workbook.read_bytes()).hexdigest()

    result = runner.invoke(
        app,
        ["upload", str(workbook), "--type", "tabular", "--name", "compass", "--tag", "x", "--json"],
    )

    assert result.exit_code == EXIT_OK, result.output
    assert json.loads(result.stdout) == {
        "uri": f"bookshelf://sha256/{digest}",
        "hash": f"sha256:{digest}",
        "tracking_id": TRACKING_ID,
        "outcome": "created",
        "dedupe": True,
        "name": "compass",
        "type": "tabular",
        "size_bytes": workbook.stat().st_size,
    }


def test_upload_says_when_the_bytes_were_already_held(
    monkeypatch: pytest.MonkeyPatch, workbook: Path
) -> None:
    _patch_client(monkeypatch, outcome="aliased")

    result = runner.invoke(app, ["upload", str(workbook), "--type", "binary"])

    assert result.exit_code == EXIT_OK, result.output
    assert "already held" in result.stdout
    # The canonical row may not be the type that was asked for, so it is read back.
    assert "timeseries" in result.stdout


def test_upload_needs_a_type(monkeypatch: pytest.MonkeyPatch, workbook: Path) -> None:
    _patch_client(monkeypatch)

    result = runner.invoke(app, ["upload", str(workbook)])

    assert result.exit_code == EXIT_USAGE


def test_upload_of_a_missing_file_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _patch_client(monkeypatch)

    result = runner.invoke(app, ["upload", "nowhere.xlsx", "--type", "binary"])

    assert result.exit_code == EXIT_USAGE
    assert recorded == []


def test_upload_maps_a_rejected_credential_to_the_auth_exit_code(
    monkeypatch: pytest.MonkeyPatch, workbook: Path
) -> None:
    _patch_client(monkeypatch, status=401)

    result = runner.invoke(app, ["upload", str(workbook), "--type", "binary"])

    assert result.exit_code == EXIT_AUTH_REQUIRED
    assert "bookshelf auth login" in result.output
