"""Tests for ``bookshelf record``, ``bookshelf validate`` and ``bookshelf publish``."""

import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._cli._runtime import (
    EXIT_INVALID_BUNDLE,
    EXIT_NETWORK,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
)
from bookshelf._core.client import BookshelfClient
from bookshelf._core.hashing import sha256_hex
from bookshelf.publisher.bundle import (
    Bundle,
    BundleBook,
    compute_book_bundle_hash,
    resource_filename,
)
from tests import _core_payloads as payloads

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
UNREACHABLE_API = "http://127.0.0.1:9"
runner = CliRunner()


def _bundle(root: Path, *, published: bool = True, entries: int = 1) -> Bundle:
    """Write a minimal replayable published book bundle to ``root``."""
    bundle = Bundle(root)
    bundle.set_book(
        BundleBook(volume="example", version="v1.0.0", visibility="public", license="MIT")
    )
    for index in range(entries):
        data = f"payload {index}".encode()
        resource = bundle.add_resource(
            data=data,
            hash_=sha256_hex(data),
            type_="document",
            tracking_id=uuid4(),
        )
        bundle.add_book_entry(name_in_book=f"entry-{index}", tracking_id=resource.tracking_id)
    if published:
        bundle.mark_book_published()
    bundle.write()
    return bundle


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


def test_validate_reports_the_bundle_summary(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle", entries=2)
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


def test_validate_human_output_names_every_field(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")

    result = runner.invoke(app, ["validate", str(bundle.root)])

    assert result.exit_code == EXIT_OK
    for label in ("Bundle", "Bundle hash", "Resources", "Entries", "Publishes"):
        assert label in result.stdout


def test_validate_defaults_to_the_bundle_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bundle(tmp_path / "bundle")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["validate", "--json"])

    assert result.exit_code == EXIT_OK
    assert _payload(result.stdout)["bundle_path"] == "bundle"


def test_validate_rejects_a_bundle_that_is_still_a_draft(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle", published=False)

    result = runner.invoke(app, ["validate", str(bundle.root)])

    assert result.exit_code == EXIT_INVALID_BUNDLE
    assert "does not record a publish operation" in _plain(result.stderr)
    assert "bookshelf record" in _plain(result.stderr)


def test_validate_rejects_a_bundle_with_no_book_framing(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    bundle.write()

    result = runner.invoke(app, ["validate", str(bundle.root)])

    assert result.exit_code == EXIT_INVALID_BUNDLE
    assert "no book framing" in _plain(result.stderr)


def test_validate_rejects_tampered_resource_bytes(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    resource = bundle.manifest.resources[0]
    byte_path = bundle.resources_dir / resource_filename(resource.hash, resource.type)
    byte_path.write_bytes(b"tampered")

    result = runner.invoke(app, ["validate", str(bundle.root)])

    assert result.exit_code == EXIT_INVALID_BUNDLE
    assert "has hash" in _plain(result.stderr)


def test_validate_rejects_an_entry_with_no_resource(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    bundle.manifest.book.entries[0].tracking_id = uuid4()  # type: ignore[union-attr]
    bundle.write()

    result = runner.invoke(app, ["validate", str(bundle.root)])

    assert result.exit_code == EXIT_INVALID_BUNDLE
    assert "has no resource" in _plain(result.stderr)


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


def test_validate_opens_no_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _bundle(tmp_path / "bundle")
    monkeypatch.setenv("BOOKSHELF_URL", UNREACHABLE_API)

    result = runner.invoke(app, ["validate", str(bundle.root), "--json"])

    assert result.exit_code == EXIT_OK


def test_validate_runs_without_the_publish_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path / "bundle")
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


class _FakeDraft:
    def __init__(self, status: str, edition: int) -> None:
        self.status = status
        self.metadata = type("Detail", (), {"edition": edition})()


class _FakeClient:
    """Stands in for the facade, recording whether replay was reached."""

    def __init__(self, status: str = "draft", edition: int = 1) -> None:
        self._status = status
        self._edition = edition
        self.draft_kwargs: dict[str, Any] = {}

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def draft_book(self, volume: str, **kwargs: Any) -> _FakeDraft:
        self.draft_kwargs = {"volume": volume, **kwargs}
        return _FakeDraft(self._status, self._edition)


def _patch_publish(
    monkeypatch: pytest.MonkeyPatch, client: _FakeClient, *, edition: int = 2
) -> list[Bundle]:
    replayed: list[Bundle] = []

    def fake_replay(bundle: Bundle, _client: Any) -> Any:
        replayed.append(bundle)
        return _FakeDraft("published", edition)

    monkeypatch.setattr("bookshelf._cli.producer.Bookshelf", lambda _url: client)
    monkeypatch.setattr("bookshelf._cli.producer.replay_bundle_sync", fake_replay)
    return replayed


def test_publish_replays_and_reports_the_edition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    client = _FakeClient(status="draft")
    replayed = _patch_publish(monkeypatch, client, edition=2)

    result = runner.invoke(app, ["publish", str(bundle.root), "--json"])

    assert result.exit_code == EXIT_OK
    summary = _payload(result.stdout)
    assert summary["outcome"] == "published"
    assert summary["volume"] == "example"
    assert summary["version"] == "v1.0.0"
    assert summary["edition"] == 2
    assert summary["resources"] == 1
    assert len(replayed) == 1
    assert client.draft_kwargs["bundle_hash"] == summary["bundle_hash"]


def test_publish_reports_a_no_op_when_the_edition_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    client = _FakeClient(status="published", edition=3)
    replayed = _patch_publish(monkeypatch, client)

    result = runner.invoke(app, ["publish", str(bundle.root), "--json"])

    assert result.exit_code == EXIT_OK
    summary = _payload(result.stdout)
    assert summary["outcome"] == "no-op"
    assert summary["edition"] == 3
    assert summary["resources"] == 0
    assert replayed == []


def test_publish_dry_run_never_replays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _bundle(tmp_path / "bundle")
    client = _FakeClient(status="draft", edition=1)
    replayed = _patch_publish(monkeypatch, client)

    result = runner.invoke(app, ["publish", str(bundle.root), "--dry-run", "--json"])

    assert result.exit_code == EXIT_OK
    summary = _payload(result.stdout)
    assert summary["outcome"] == "would-publish"
    assert summary["edition"] == 1
    assert replayed == []


def test_publish_dry_run_reports_a_no_op_for_a_published_edition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    client = _FakeClient(status="published", edition=4)
    _patch_publish(monkeypatch, client)

    result = runner.invoke(app, ["publish", str(bundle.root), "--dry-run", "--json"])

    assert result.exit_code == EXIT_OK
    assert _payload(result.stdout)["outcome"] == "no-op"


def test_publish_forwards_the_recorded_framing_to_the_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    client = _FakeClient(status="draft")
    _patch_publish(monkeypatch, client)

    result = runner.invoke(app, ["publish", str(bundle.root), "--json"])

    assert result.exit_code == EXIT_OK
    assert client.draft_kwargs["volume"] == "example"
    assert client.draft_kwargs["version"] == "v1.0.0"
    assert client.draft_kwargs["visibility"] == "public"
    assert client.draft_kwargs["license"] == "MIT"


def test_publish_rejects_a_token_flag(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")

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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    monkeypatch.setenv("BOOKSHELF_URL", UNREACHABLE_API)

    result = runner.invoke(app, ["publish", str(bundle.root)])

    assert result.exit_code == EXIT_NETWORK


def test_recorded_and_validated_bundle_hashes_agree(tmp_path: Path) -> None:
    """The hash a caller validates is the hash publish drafts against."""
    bundle = _bundle(tmp_path / "bundle")
    client = _FakeClient(status="draft")

    validated = runner.invoke(app, ["validate", str(bundle.root), "--json"])
    assert validated.exit_code == EXIT_OK

    with pytest.MonkeyPatch.context() as patch:
        _patch_publish(patch, client)
        published = runner.invoke(app, ["publish", str(bundle.root), "--json"])

    assert published.exit_code == EXIT_OK
    assert _payload(published.stdout)["bundle_hash"] == _payload(validated.stdout)["bundle_hash"]


def test_tracking_ids_round_trip_as_uuids(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")

    reloaded = Bundle.read(bundle.root)

    assert isinstance(reloaded.manifest.resources[0].tracking_id, UUID)
