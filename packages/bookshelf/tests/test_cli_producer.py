"""Tests for ``bookshelf record``, ``bookshelf validate`` and ``bookshelf publish``."""

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from bookshelf._cli import app, producer
from bookshelf._cli._runtime import (
    EXIT_INVALID_BUNDLE,
    EXIT_NETWORK,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
)
from bookshelf._core.client import BookshelfClient
from bookshelf.publisher.bundle import (
    Bundle,
    compute_book_bundle_hash,
    resource_filename,
)
from bookshelf.publisher.publish import PublishOutcome
from tests import _core_payloads as payloads
from tests.conftest import BundleFactory

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
UNREACHABLE_API = "http://127.0.0.1:9"
runner = CliRunner()


def _recipe(path: Path, *, notebook: str | None = "build.py") -> Path:
    """Write a minimal valid record recipe, optionally without a notebook."""
    lines = ["collection: example", "license: MIT"]
    if notebook is not None:
        lines.append(f"notebook: {notebook}")
    path.write_text("\n".join(lines) + "\n")
    return path


def _payload(output: str) -> dict[str, Any]:
    return json.loads(output)  # type: ignore[no-any-return]


def _plain(text: str) -> str:
    """Strip ANSI styling, which typer emits for its own usage errors under CI."""
    return _ANSI.sub("", text)


def test_validate_reports_the_bundle_summary(make_bundle: BundleFactory) -> None:
    bundle = make_bundle(entries=2)
    # Recomputed from what landed on disk, so the reported hash is checked
    # against an independent value rather than against itself.
    expected_hash = compute_book_bundle_hash(Bundle.read(bundle.root).manifest)

    result = runner.invoke(app, ["validate", str(bundle.root), "--json"])

    assert result.exit_code == EXIT_OK
    assert _payload(result.stdout) == {
        "bundle_path": str(bundle.root),
        "bundle_hash": expected_hash,
        "resources": 2,
        "book_entries": 2,
        "published": True,
    }


def test_validate_human_output_names_every_field(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()

    result = runner.invoke(app, ["validate", str(bundle.root)])

    assert result.exit_code == EXIT_OK
    for label in ("Bundle", "Bundle hash", "Resources", "Entries", "Publishes"):
        assert label in result.stdout


def test_validate_defaults_to_the_bundle_directory(
    tmp_path: Path, make_bundle: BundleFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_bundle()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["validate", "--json"])

    assert result.exit_code == EXIT_OK
    assert _payload(result.stdout)["bundle_path"] == "bundle"


def test_validate_renders_a_refused_bundle_with_its_remedy(make_bundle: BundleFactory) -> None:
    """The bundle names the invariant, and the CLI adds the exit code and the fix."""
    bundle = make_bundle(published=False)

    result = runner.invoke(app, ["validate", str(bundle.root)])

    assert result.exit_code == EXIT_INVALID_BUNDLE
    assert "does not record a publish operation" in _plain(result.stderr)
    assert "bookshelf record" in _plain(result.stderr)


def test_validate_reports_absent_resource_bytes_as_an_invalid_bundle(
    make_bundle: BundleFactory,
) -> None:
    """A manifest record whose byte file is gone exits 7 rather than raising through."""
    bundle = make_bundle()
    resource = bundle.manifest.resources[0]
    (bundle.resources_dir / resource_filename(resource.hash, resource.type)).unlink()

    result = runner.invoke(app, ["validate", str(bundle.root)])

    assert result.exit_code == EXIT_INVALID_BUNDLE
    assert "has no bytes in the bundle" in _plain(result.stderr)


def test_validate_reports_a_crafted_hash_as_an_invalid_bundle(make_bundle: BundleFactory) -> None:
    """The manifest read fine, so the refusal must not be rendered as an unreadable bundle."""
    bundle = make_bundle()
    bundle.manifest.resources[0].hash = "sha256:../../etc/passwd"
    bundle.write()

    result = runner.invoke(app, ["validate", str(bundle.root)])

    assert result.exit_code == EXIT_INVALID_BUNDLE
    assert "non-canonical hash" in _plain(result.stderr)
    assert "cannot read a bundle" not in _plain(result.stderr)


def test_validate_rejects_a_missing_bundle(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(tmp_path / "absent")])

    assert result.exit_code == EXIT_INVALID_BUNDLE
    assert "cannot read a bundle" in _plain(result.stderr)


def test_validate_rejects_a_malformed_manifest(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "manifest.lock").write_text("schema_version: 99.0.0\n")

    result = runner.invoke(app, ["validate", str(root)])

    assert result.exit_code == EXIT_INVALID_BUNDLE


def test_validate_opens_no_socket(
    make_bundle: BundleFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = make_bundle()
    monkeypatch.setenv("BOOKSHELF_URL", UNREACHABLE_API)

    result = runner.invoke(app, ["validate", str(bundle.root), "--json"])

    assert result.exit_code == EXIT_OK


def test_validate_runs_without_the_publish_extra(
    make_bundle: BundleFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = make_bundle()
    monkeypatch.setattr("bookshelf._cli.producer.importlib.util.find_spec", lambda _: None)

    result = runner.invoke(app, ["validate", str(bundle.root), "--json"])

    assert result.exit_code == EXIT_OK


def test_record_refuses_an_existing_bundle_without_force(tmp_path: Path) -> None:
    existing = tmp_path / "bundle"
    existing.mkdir()

    result = runner.invoke(
        app,
        ["record", "--recipe", str(tmp_path / "bookshelf.yaml"), "--bundle", str(existing)],
    )

    assert result.exit_code == EXIT_USAGE
    assert "already exists" in _plain(result.stderr)
    assert "--force" in _plain(result.stderr)


def test_record_names_the_fix_when_no_build_file_resolves(tmp_path: Path) -> None:
    recipe = _recipe(tmp_path / "bookshelf.yaml", notebook=None)

    result = runner.invoke(
        app, ["record", "--recipe", str(recipe), "--bundle", str(tmp_path / "bundle")]
    )

    assert result.exit_code == EXIT_USAGE
    assert "sets no notebook" in _plain(result.stderr)
    assert "bookshelf record BUILD" in _plain(result.stderr)


def test_record_names_the_fix_when_the_build_file_is_absent(tmp_path: Path) -> None:
    recipe = _recipe(tmp_path / "bookshelf.yaml")

    result = runner.invoke(
        app,
        [
            "record",
            str(tmp_path / "absent.py"),
            "--recipe",
            str(recipe),
            "--bundle",
            str(tmp_path / "bundle"),
        ],
    )

    assert result.exit_code == EXIT_USAGE
    assert "build file not found" in _plain(result.stderr)


def test_record_names_the_fix_when_the_build_file_is_not_python(tmp_path: Path) -> None:
    recipe = _recipe(tmp_path / "bookshelf.yaml")
    notebook = tmp_path / "build.ipynb"
    notebook.write_text("{}")

    result = runner.invoke(
        app,
        ["record", str(notebook), "--recipe", str(recipe), "--bundle", str(tmp_path / "bundle")],
    )

    assert result.exit_code == EXIT_USAGE
    assert "standalone Jupytext .py build file" in _plain(result.stderr)


def test_record_names_the_fix_when_the_recipe_is_missing(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "record",
            "--recipe",
            str(tmp_path / "absent.yaml"),
            "--bundle",
            str(tmp_path / "bundle"),
        ],
    )

    assert result.exit_code == EXIT_USAGE
    assert "cannot read the recipe" in _plain(result.stderr)
    assert "--recipe" in _plain(result.stderr)


def test_record_names_the_fix_when_the_recipe_is_malformed(tmp_path: Path) -> None:
    recipe = tmp_path / "bookshelf.yaml"
    recipe.write_text("collection: example\n")

    result = runner.invoke(
        app, ["record", "--recipe", str(recipe), "--bundle", str(tmp_path / "bundle")]
    )

    assert result.exit_code == EXIT_USAGE
    assert "non-empty license" in _plain(result.stderr)


def test_record_validates_the_recipe_even_when_a_build_file_is_given(tmp_path: Path) -> None:
    """An explicit build file must not skip recipe validation, which run_record would fail on."""
    build = tmp_path / "build.py"
    build.write_text("x = 1\n")
    recipe = tmp_path / "bookshelf.yaml"
    recipe.write_text("collection: example\n")

    result = runner.invoke(
        app,
        ["record", str(build), "--recipe", str(recipe), "--bundle", str(tmp_path / "bundle")],
    )

    assert result.exit_code == EXIT_USAGE


def test_record_reports_a_missing_publish_extra_as_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("bookshelf._cli.producer.importlib.util.find_spec", lambda _: None)

    result = runner.invoke(app, ["record", "--bundle", str(tmp_path / "bundle")])

    assert result.exit_code == EXIT_USAGE
    assert "bookshelf[publish]" in _plain(result.stderr)


def test_record_gates_only_on_what_the_capture_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    """A library the capture never imports must not stand between a producer and a record."""
    monkeypatch.setattr(
        "bookshelf._cli.producer.importlib.util.find_spec",
        lambda name: None if name == "papermill" else object(),
    )

    producer._require_publish_extra()


def test_record_passes_parameters_and_paths_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_run_record(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {
            "bundle_path": str(kwargs["bundle_path"]),
            "manifest_path": str(kwargs["bundle_path"] / "manifest.lock"),
            "resources": 1,
            "book_entries": 1,
            "published": True,
        }

    monkeypatch.setattr("bookshelf._cli.producer.run_record", fake_run_record)
    recipe = _recipe(tmp_path / "bookshelf.yaml")
    build = tmp_path / "build.py"
    build.write_text("x = 1\n")

    result = runner.invoke(
        app,
        [
            "record",
            str(build),
            "--recipe",
            str(recipe),
            "--bundle",
            str(tmp_path / "bundle"),
            "-p",
            "tag=v5.0",
            "-p",
            "revision=5.0",
            "-p",
            "strict=true",
            "--json",
        ],
    )

    assert result.exit_code == EXIT_OK
    # The CLI resolves the build path, so run_record is handed one it has already accepted.
    assert seen["build_path"] == build.resolve()
    assert seen["recipe_path"] == recipe
    # Values are YAML scalars, so a bare 5.0 arrives as a float and not a string.
    assert seen["parameters"] == {"tag": "v5.0", "revision": 5.0, "strict": True}
    assert _payload(result.stdout)["resources"] == 1


def test_record_resolves_the_build_file_from_the_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting BUILD falls back to the recipe's notebook, which is how a bare record runs."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "bookshelf._cli.producer.run_record", lambda **kwargs: seen.update(kwargs) or {}
    )
    _recipe(tmp_path / "bookshelf.yaml")
    (tmp_path / "build.py").write_text("x = 1\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["record", "--bundle", str(tmp_path / "bundle"), "--json"])

    assert result.exit_code == EXIT_OK
    assert seen["build_path"] == (tmp_path / "build.py").resolve()


def test_record_rejects_a_malformed_parameter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("bookshelf._cli.producer.run_record", lambda **_: {})
    recipe = _recipe(tmp_path / "bookshelf.yaml")
    (tmp_path / "build.py").write_text("x = 1\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["record", "--recipe", str(recipe), "--bundle", str(tmp_path / "bundle"), "-p", "nonsense"],
    )

    assert result.exit_code == EXIT_USAGE
    assert "expected key=value" in _plain(result.stderr)


def _patch_discard(
    monkeypatch: pytest.MonkeyPatch, *, status: str = "draft", edition: int = 1
) -> list[httpx.Request]:
    """Route ``discard`` at a mock transport that lists one book and accepts the deletion."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(
            200,
            json={
                "items": [payloads.book_list_item(status=status, edition=edition)],
                "total": 1,
                "limit": 1000,
                "offset": 0,
                "has_more": False,
            },
        )

    monkeypatch.setattr(
        "bookshelf._cli.producer.BookshelfClient",
        lambda url: BookshelfClient(url, auth=None, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setenv("BOOKSHELF_URL", "https://bookshelf.test")
    return recorded


def test_discard_deletes_the_draft_edition(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _patch_discard(monkeypatch)

    result = runner.invoke(app, ["discard", "example@v1.0.0_e001", "--json"])

    assert result.exit_code == EXIT_OK
    assert _payload(result.stdout) == {
        "outcome": "discarded",
        "book_id": "b1",
        "address": "example@v1.0.0_e001",
    }
    assert [(request.method, request.url.path) for request in recorded] == [
        ("GET", "/v1/books"),
        ("DELETE", "/v1/books/b1"),
    ]


def test_discard_walks_past_the_first_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """An edition beyond the first page must be deleted, not reported as absent."""
    seen_offsets: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(204)
        offset = request.url.params.get("offset", "0")
        seen_offsets.append(offset)
        first_page = offset == "0"
        return httpx.Response(
            200,
            json={
                "items": [payloads.book_list_item(edition=9 if first_page else 1)],
                "total": 2,
                "limit": 100,
                "offset": int(offset),
                "has_more": first_page,
            },
        )

    monkeypatch.setattr(
        "bookshelf._cli.producer.BookshelfClient",
        lambda url: BookshelfClient(url, auth=None, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setenv("BOOKSHELF_URL", "https://bookshelf.test")

    result = runner.invoke(app, ["discard", "example@v1.0.0_e001", "--json"])

    assert result.exit_code == EXIT_OK
    assert seen_offsets == ["0", "100"]
    assert _payload(result.stdout)["book_id"] == "b1"


def test_discard_refuses_a_published_edition_before_asking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _patch_discard(monkeypatch, status="published")

    result = runner.invoke(app, ["discard", "example@v1.0.0_e001"])

    assert result.exit_code == EXIT_USAGE
    assert "only a draft can be discarded" in _plain(result.stderr)
    assert [request.method for request in recorded] == ["GET"]


def test_discard_reports_an_edition_that_is_not_there(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_discard(monkeypatch, edition=2)

    result = runner.invoke(app, ["discard", "example@v1.0.0_e001"])

    assert result.exit_code == EXIT_NOT_FOUND
    assert "does not resolve to a book" in _plain(result.stderr)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("example", "needs an exact edition"),
        ("example@v1.0.0", "needs an exact edition"),
        ("example@v1.0.0_e001/by_country", "not a file within one"),
    ],
)
def test_discard_rejects_an_address_that_is_not_one_edition(
    address: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = _patch_discard(monkeypatch)

    result = runner.invoke(app, ["discard", address])

    assert result.exit_code == EXIT_USAGE
    assert expected in _plain(result.stderr)
    assert recorded == []


def _patch_publish(
    monkeypatch: pytest.MonkeyPatch, outcome: PublishOutcome
) -> list[tuple[Bundle, bool]]:
    """Answer the publisher with ``outcome``, recording the bundle and flag the command passed."""
    calls: list[tuple[Bundle, bool]] = []

    def fake_publish(bundle: Bundle, _client: Any, *, dry_run: bool = False) -> PublishOutcome:
        calls.append((bundle, dry_run))
        return outcome

    # The command still builds a real client around the stubbed publisher,
    # so point it somewhere that is not the production deployment.
    monkeypatch.setenv("BOOKSHELF_URL", UNREACHABLE_API)
    monkeypatch.setattr("bookshelf._cli.producer.publish_bundle", fake_publish)
    return calls


def test_publish_renders_the_outcome(
    make_bundle: BundleFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = make_bundle()
    outcome = PublishOutcome(kind="published", edition=2, resources=1, bundle_hash="b" * 64)
    calls = _patch_publish(monkeypatch, outcome)

    result = runner.invoke(app, ["publish", str(bundle.root), "--json"])

    assert result.exit_code == EXIT_OK
    summary = _payload(result.stdout)
    assert summary["outcome"] == "published"
    assert summary["volume"] == "example"
    assert summary["version"] == "v1.0.0"
    assert summary["edition"] == 2
    assert summary["resources"] == 1
    assert summary["bundle_hash"] == "b" * 64
    assert [dry_run for _bundle_arg, dry_run in calls] == [False]


def test_publish_renders_a_no_op(
    make_bundle: BundleFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = make_bundle()
    _patch_publish(
        monkeypatch, PublishOutcome(kind="no-op", edition=3, resources=0, bundle_hash="c" * 64)
    )

    result = runner.invoke(app, ["publish", str(bundle.root), "--json"])

    assert result.exit_code == EXIT_OK
    summary = _payload(result.stdout)
    assert summary["outcome"] == "no-op"
    assert summary["edition"] == 3
    assert summary["resources"] == 0


def test_publish_dry_run_asks_the_publisher_not_to_write(
    make_bundle: BundleFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = make_bundle()
    calls = _patch_publish(
        monkeypatch,
        PublishOutcome(kind="would-publish", edition=1, resources=1, bundle_hash="d" * 64),
    )

    result = runner.invoke(app, ["publish", str(bundle.root), "--dry-run", "--json"])

    assert result.exit_code == EXIT_OK
    summary = _payload(result.stdout)
    assert summary["outcome"] == "would-publish"
    assert summary["edition"] == 1
    assert [dry_run for _bundle_arg, dry_run in calls] == [True]


def test_publish_rejects_a_token_flag(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()

    result = runner.invoke(app, ["publish", str(bundle.root), "--token", "secret"])

    assert result.exit_code == EXIT_USAGE
    assert "--token" in _plain(result.stderr)


def test_publish_rejects_an_invalid_bundle_before_reaching_the_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", UNREACHABLE_API)
    root = tmp_path / "bundle"
    Bundle(root).write()

    result = runner.invoke(app, ["publish", str(root)])

    assert result.exit_code == EXIT_INVALID_BUNDLE


def test_publish_uses_the_network_exit_code_when_the_api_is_unreachable(
    make_bundle: BundleFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = make_bundle()
    monkeypatch.setenv("BOOKSHELF_URL", UNREACHABLE_API)

    result = runner.invoke(app, ["publish", str(bundle.root)])

    assert result.exit_code == EXIT_NETWORK
