"""Tests for ``bookshelf preview upload``."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._cli._runtime import (
    EXIT_AUTH_REQUIRED,
    EXIT_INVALID_BUNDLE,
    EXIT_NETWORK,
    EXIT_OK,
    EXIT_USAGE,
)
from bookshelf._core.client import BookshelfClient
from tests._preview import BASE_URL, PREVIEW_ID, SHA, PreviewDeployment
from tests.conftest import BundleFactory

UNREACHABLE_API = "http://127.0.0.1:9"
runner = CliRunner()


def _arguments(*bundles: Path) -> list[str]:
    return [
        "preview",
        "upload",
        *(str(bundle) for bundle in bundles),
        "--repository",
        "climate-resource/feedstock",
        "--pr",
        "7",
        "--pr-url",
        "https://github.com/climate-resource/feedstock/pull/7",
        "--head-sha",
        SHA,
        "--main-sha",
        SHA,
        "--tree",
        SHA,
        "--run-id",
        "42",
    ]


@pytest.fixture
def oidc_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bookshelf._cli.preview.fetch_actions_token", lambda _audience: "oidc-jwt")


@pytest.fixture
def deployment(monkeypatch: pytest.MonkeyPatch) -> PreviewDeployment:
    deployment = PreviewDeployment()
    monkeypatch.setattr(
        "bookshelf._cli.preview.BookshelfClient",
        lambda url, auth: BookshelfClient(url, auth=auth, transport=deployment.transport()),
    )
    monkeypatch.setenv("BOOKSHELF_URL", BASE_URL)
    return deployment


def _payload(output: str) -> dict[str, Any]:
    return json.loads(output)  # type: ignore[no-any-return]


@pytest.mark.usefixtures("oidc_token")
def test_upload_prints_the_sealed_preview_as_json(
    make_bundle: BundleFactory, deployment: PreviewDeployment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOKSHELF_TOKEN", "ambient-token")
    bundle = make_bundle()

    result = runner.invoke(app, [*_arguments(bundle.root), "--json"])

    assert result.exit_code == EXIT_OK, result.output
    assert _payload(result.stdout) == {
        "preview_id": PREVIEW_ID,
        "proposal_url": f"{BASE_URL}/v1/proposals/climate-resource%2Ffeedstock/7",
        "preview_url": f"{BASE_URL}/previews/{PREVIEW_ID}",
        "state": "sealed",
        "books": [
            {"volume": "example", "version": "v1.0.0", "uploaded": True, "baseline": "absent"}
        ],
    }
    api_requests = [r for r in deployment.requests if r.url.host != "s3.example"]
    assert {r.headers["authorization"] for r in api_requests} == {"Bearer oidc-jwt"}


@pytest.mark.usefixtures("oidc_token", "deployment")
def test_upload_human_output_names_the_links(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()

    result = runner.invoke(app, _arguments(bundle.root))

    assert result.exit_code == EXIT_OK, result.output
    for label in ("Preview", "State", "Proposal", "Preview URL", "Book"):
        assert label in result.stdout
    assert "example v1.0.0, uploaded, absent" in result.stdout


@pytest.mark.usefixtures("oidc_token", "deployment")
def test_upload_without_a_repository_is_a_usage_error(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    arguments = _arguments(bundle.root)
    index = arguments.index("--repository")
    del arguments[index : index + 2]

    result = runner.invoke(app, arguments)

    assert result.exit_code == EXIT_USAGE


@pytest.mark.usefixtures("oidc_token", "deployment")
def test_upload_with_a_malformed_sha_is_a_usage_error(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    arguments = _arguments(bundle.root)
    arguments[arguments.index("--tree") + 1] = "not-a-sha"

    result = runner.invoke(app, arguments)

    assert result.exit_code == EXIT_USAGE


def test_upload_outside_actions_asks_for_the_id_token_permission(
    make_bundle: BundleFactory, deployment: PreviewDeployment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ACTIONS_ID_TOKEN_REQUEST_URL", raising=False)
    monkeypatch.delenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", raising=False)
    monkeypatch.setenv("BOOKSHELF_TOKEN", "ambient-token")
    bundle = make_bundle()

    result = runner.invoke(app, _arguments(bundle.root))

    assert result.exit_code == EXIT_AUTH_REQUIRED
    assert "id-token: write" in result.stderr
    assert deployment.requests == []


@pytest.mark.usefixtures("oidc_token")
def test_upload_to_an_unreachable_deployment_is_a_network_error(
    make_bundle: BundleFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", UNREACHABLE_API)
    bundle = make_bundle()

    result = runner.invoke(app, _arguments(bundle.root))

    assert result.exit_code == EXIT_NETWORK


@pytest.mark.usefixtures("oidc_token")
def test_upload_with_an_invalid_bundle_fails_the_preview(
    make_bundle: BundleFactory, deployment: PreviewDeployment
) -> None:
    bundle = make_bundle(published=False)

    result = runner.invoke(app, [*_arguments(bundle.root), "--json"])

    assert result.exit_code == EXIT_INVALID_BUNDLE
    assert _payload(result.stdout)["state"] == "failed"
    assert "does not record a publish operation" in result.stderr
    assert len(deployment.sent("/fail")) == 1


@pytest.mark.usefixtures("oidc_token", "deployment")
def test_upload_of_an_unreadable_bundle_is_an_invalid_bundle(tmp_path: Path) -> None:
    result = runner.invoke(app, _arguments(tmp_path / "missing"))

    assert result.exit_code == EXIT_INVALID_BUNDLE
    assert "missing" in result.stderr
