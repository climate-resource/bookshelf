"""Failure, recovery, and promotion tests for the model generation driver."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


@pytest.fixture
def generator(tmp_path: Path) -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "generate_models.py"
    spec = importlib.util.spec_from_file_location("bookshelf_generate_models_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    sdk = tmp_path / "sdk"
    package = sdk / "src" / "bookshelf"
    package.mkdir(parents=True)
    contract = {
        "openapi": "3.1.0",
        "info": {"title": "test", "version": "0.1.0"},
        "components": {"schemas": {"Probe": {"type": "object"}}},
    }
    (sdk / "openapi.json").write_text(json.dumps(contract))
    module.SDK_ROOT = sdk
    module.PACKAGE_ROOT = package
    module.LIVE_TREE = package / "_generated"
    module.OPENAPI_PATH = sdk / "openapi.json"
    return module


def _header(module: ModuleType, version: str = "0.1.0") -> str:
    return module._header(version)  # type: ignore[no-any-return]


def _seed_tree(
    module: ModuleType,
    path: Path,
    *,
    valid: bool = True,
    marker: str = "old",
    version: str = "0.1.0",
) -> None:
    path.mkdir(parents=True)
    if not valid:
        (path / "broken.txt").write_text(marker)
        return
    (path / "models.py").write_text(_header(module, version) + f'\nMARKER = "{marker}"\n')
    (path / "__init__.py").write_text(
        _header(module, version)
        + "\nfrom . import models as models\n\n"
        + f'OPENAPI_VERSION = "{version}"\n\n'
        + '__all__ = ["OPENAPI_VERSION", "models"]\n'
    )


def _manifest(path: Path) -> dict[str, str]:
    return {
        item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


class FakeRunner:
    def __init__(self, module: ModuleType, fail: str | None = None, output: str = "valid") -> None:
        self.module = module
        self.fail = fail
        self.output = output
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, boundary: str, command: Any) -> subprocess.CompletedProcess[str]:
        args = list(command)
        self.calls.append((boundary, args))
        if boundary == self.fail:
            raise self.module.GenerationError(f"injected {boundary}")
        if boundary.endswith(":isolated-import"):
            return self.module._default_runner(boundary, args)
        if boundary == "datamodel-code-generator-version":
            return subprocess.CompletedProcess(args, 0, "datamodel-codegen 0.68.1\n", "")
        if boundary == "ruff-version":
            return subprocess.CompletedProcess(args, 0, "ruff 0.15.0\n", "")
        if boundary == "datamodel-codegen":
            output_path = Path(args[args.index("--output") + 1])
            if self.output == "invalid-syntax":
                output_path.write_text("class :\n")
            elif self.output == "failed-import":
                output_path.write_text('raise RuntimeError("import failed")\n')
            else:
                output_path.write_text('MARKER = "new"\n')
            if self.output == "unexpected-manifest":
                (output_path.parent / "unexpected.py").write_text("")
        return subprocess.CompletedProcess(args, 0, "", "")


def _write_contract(module: ModuleType, value: object) -> None:
    module.OPENAPI_PATH.write_text(json.dumps(value))


@pytest.mark.parametrize(
    "contract,error",
    [
        (
            {
                "openapi": "3.0.3",
                "info": {"version": "0.1.0"},
                "components": {"schemas": {"X": {}}},
            },
            "openapi ==",
        ),
        (
            {"openapi": "3.1.0", "components": {"schemas": {"X": {}}}},
            "info object",
        ),
        (
            {
                "openapi": "3.1.0",
                "info": {"version": "   "},
                "components": {"schemas": {"X": {}}},
            },
            "non-blank",
        ),
        (
            {"openapi": "3.1.0", "info": {"version": "0.1.0"}},
            "components.schemas",
        ),
        (
            {
                "openapi": "3.1.0",
                "info": {"version": "0.1.0"},
                "components": {"schemas": {}},
            },
            "components.schemas",
        ),
    ],
)
def test_invalid_contract_stops_before_tools(
    generator: ModuleType, contract: object, error: str
) -> None:
    _write_contract(generator, contract)
    runner = FakeRunner(generator)
    with pytest.raises(generator.GenerationError, match=error):
        generator.generate(runner=runner)
    assert runner.calls == []


@pytest.mark.parametrize("failure", ["datamodel-codegen", "ruff-check", "ruff-format"])
def test_tool_failure_preserves_live_tree(generator: ModuleType, failure: str) -> None:
    _seed_tree(generator, generator.LIVE_TREE)
    before = _manifest(generator.LIVE_TREE)
    with pytest.raises(generator.GenerationError, match="injected"):
        generator.generate(runner=FakeRunner(generator, fail=failure))
    assert _manifest(generator.LIVE_TREE) == before
    assert not list(generator.PACKAGE_ROOT.glob("._generated.*.*"))


@pytest.mark.parametrize(
    "output,error",
    [
        ("invalid-syntax", "Syntax compilation failed"),
        ("failed-import", "temporary:isolated-import failed"),
        ("unexpected-manifest", "Unexpected generated manifest"),
    ],
)
def test_invalid_generated_output_is_not_promoted(
    generator: ModuleType, output: str, error: str
) -> None:
    _seed_tree(generator, generator.LIVE_TREE)
    before = _manifest(generator.LIVE_TREE)
    with pytest.raises(generator.GenerationError, match=error):
        generator.generate(runner=FakeRunner(generator, output=output))
    assert _manifest(generator.LIVE_TREE) == before


def test_generation_updates_a_valid_prior_version_tree(generator: ModuleType) -> None:
    _seed_tree(generator, generator.LIVE_TREE, version="0.1.0")
    contract = json.loads(generator.OPENAPI_PATH.read_text())
    contract["info"]["version"] = "0.2.0"
    _write_contract(generator, contract)

    generator.generate(runner=FakeRunner(generator))

    assert _manifest(generator.LIVE_TREE)
    assert "# OPENAPI_VERSION: 0.2.0" in (generator.LIVE_TREE / "models.py").read_text()
    assert 'OPENAPI_VERSION = "0.2.0"' in (generator.LIVE_TREE / "__init__.py").read_text()


def test_generation_recovers_a_prior_version_backup_then_updates(generator: ModuleType) -> None:
    backup = generator.PACKAGE_ROOT / "._generated.backup.interrupted"
    _seed_tree(generator, backup, version="0.1.0")
    contract = json.loads(generator.OPENAPI_PATH.read_text())
    contract["info"]["version"] = "0.2.0"
    _write_contract(generator, contract)

    generator.generate(runner=FakeRunner(generator))

    assert "# OPENAPI_VERSION: 0.2.0" in (generator.LIVE_TREE / "models.py").read_text()
    assert not list(generator.PACKAGE_ROOT.glob("._generated.backup.*"))
    assert not list(generator.PACKAGE_ROOT.glob("._generated.tmp.*"))


def test_exact_generator_flags_are_locked(generator: ModuleType) -> None:
    runner = FakeRunner(generator)
    generator.generate(runner=runner)
    command = next(args for boundary, args in runner.calls if boundary == "datamodel-codegen")
    assert command == [
        "datamodel-codegen",
        "--input",
        str(generator.OPENAPI_PATH),
        "--input-file-type",
        "openapi",
        "--schema-version",
        "3.1",
        "--schema-version-mode",
        "strict",
        "--openapi-scopes",
        "schemas",
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--target-python-version",
        "3.12",
        "--disable-timestamp",
        "--formatters",
        "builtin",
        "--use-annotated",
        "--set-default-enum-member",
        "--output",
        str(generator.LIVE_TREE),
    ][:-1] + [command[-1]]
    assert Path(command[-1]).name == "models.py"
    assert Path(command[-1]).parent.name.startswith("._generated.tmp.")


def test_first_generation_succeeds_without_residue(generator: ModuleType) -> None:
    generator.generate(runner=FakeRunner(generator))
    assert _manifest(generator.LIVE_TREE)
    assert not list(generator.PACKAGE_ROOT.glob("._generated.tmp.*"))
    assert not list(generator.PACKAGE_ROOT.glob("._generated.backup.*"))


def test_startup_no_live_no_backup_cleans_abandoned_temporary(generator: ModuleType) -> None:
    abandoned = generator.PACKAGE_ROOT / "._generated.tmp.abandoned"
    _seed_tree(generator, abandoned)
    generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert not abandoned.exists()
    assert not generator.LIVE_TREE.exists()


def test_startup_accepts_runtime_bytecode_cache(generator: ModuleType) -> None:
    _seed_tree(generator, generator.LIVE_TREE)
    cache = generator.LIVE_TREE / "__pycache__"
    cache.mkdir()
    (cache / "models.cpython-314.pyc").write_bytes(b"ignored runtime cache")
    generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert generator.LIVE_TREE.is_dir()


def test_startup_valid_live_no_backup_cleans_temporary(generator: ModuleType) -> None:
    _seed_tree(generator, generator.LIVE_TREE)
    abandoned = generator.PACKAGE_ROOT / "._generated.tmp.abandoned"
    _seed_tree(generator, abandoned)
    before = _manifest(generator.LIVE_TREE)
    generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert _manifest(generator.LIVE_TREE) == before
    assert not abandoned.exists()


def test_startup_restores_sole_valid_backup_before_cleaning_temporary(
    generator: ModuleType,
) -> None:
    backup = generator.PACKAGE_ROOT / "._generated.backup.one"
    abandoned = generator.PACKAGE_ROOT / "._generated.tmp.abandoned"
    _seed_tree(generator, backup, marker="backup")
    _seed_tree(generator, abandoned, marker="temporary")
    expected = _manifest(backup)
    generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert _manifest(generator.LIVE_TREE) == expected
    assert not backup.exists()
    assert not abandoned.exists()


def test_startup_preserves_invalid_sole_backup_and_temporary(generator: ModuleType) -> None:
    backup = generator.PACKAGE_ROOT / "._generated.backup.one"
    abandoned = generator.PACKAGE_ROOT / "._generated.tmp.abandoned"
    _seed_tree(generator, backup, valid=False)
    _seed_tree(generator, abandoned)
    before = {backup: _manifest(backup), abandoned: _manifest(abandoned)}
    with pytest.raises(generator.GenerationError, match="sole backup"):
        generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert {path: _manifest(path) for path in before} == before


def test_startup_keeps_valid_live_and_removes_one_backup(generator: ModuleType) -> None:
    backup = generator.PACKAGE_ROOT / "._generated.backup.one"
    abandoned = generator.PACKAGE_ROOT / "._generated.tmp.abandoned"
    _seed_tree(generator, generator.LIVE_TREE, marker="live")
    _seed_tree(generator, backup, marker="backup")
    _seed_tree(generator, abandoned)
    expected = _manifest(generator.LIVE_TREE)
    generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert _manifest(generator.LIVE_TREE) == expected
    assert not backup.exists()
    assert not abandoned.exists()


def test_startup_preserves_invalid_live_valid_backup_and_temporary(
    generator: ModuleType,
) -> None:
    backup = generator.PACKAGE_ROOT / "._generated.backup.one"
    abandoned = generator.PACKAGE_ROOT / "._generated.tmp.abandoned"
    _seed_tree(generator, generator.LIVE_TREE, valid=False, marker="live")
    _seed_tree(generator, backup, marker="backup")
    _seed_tree(generator, abandoned)
    paths = [generator.LIVE_TREE, backup, abandoned]
    before = {path: _manifest(path) for path in paths}
    with pytest.raises(generator.GenerationError, match="live is invalid"):
        generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert {path: _manifest(path) for path in paths} == before


@pytest.mark.parametrize("live_state", ["absent", "valid", "invalid"])
def test_multiple_backups_preserve_every_path(generator: ModuleType, live_state: str) -> None:
    paths = [
        generator.PACKAGE_ROOT / "._generated.backup.one",
        generator.PACKAGE_ROOT / "._generated.backup.two",
        generator.PACKAGE_ROOT / "._generated.tmp.abandoned",
    ]
    for path in paths:
        _seed_tree(generator, path)
    if live_state != "absent":
        _seed_tree(generator, generator.LIVE_TREE, valid=live_state == "valid")
        paths.append(generator.LIVE_TREE)
    before = {path: _manifest(path) for path in paths}
    with pytest.raises(generator.GenerationError, match="multiple backup"):
        generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert {path: _manifest(path) for path in paths} == before


@pytest.mark.parametrize(
    "boundary",
    [
        "before_live_to_backup",
        "after_live_to_backup",
        "before_temporary_to_live",
        "after_temporary_to_live",
        "before_post_promotion_validation",
        "after_post_promotion_validation",
    ],
)
def test_promotion_boundary_failure_restores_previous_tree(
    generator: ModuleType, boundary: str
) -> None:
    _seed_tree(generator, generator.LIVE_TREE, marker="previous")
    before = _manifest(generator.LIVE_TREE)

    def hook(current: str) -> None:
        if current == boundary:
            raise OSError(f"injected {boundary}")

    with pytest.raises(generator.GenerationError):
        generator.generate(runner=FakeRunner(generator), hook=hook)
    assert _manifest(generator.LIVE_TREE) == before
    assert not list(generator.PACKAGE_ROOT.glob("._generated.tmp.*"))
    assert not list(generator.PACKAGE_ROOT.glob("._generated.backup.*"))


def test_post_promotion_validation_failure_restores_previous_tree(generator: ModuleType) -> None:
    _seed_tree(generator, generator.LIVE_TREE, marker="previous")
    before = _manifest(generator.LIVE_TREE)
    runner = FakeRunner(generator, fail="post-promotion-live:isolated-import")
    with pytest.raises(generator.GenerationError, match="previous generated tree restored"):
        generator.generate(runner=runner)
    assert _manifest(generator.LIVE_TREE) == before
    assert not list(generator.PACKAGE_ROOT.glob("._generated.tmp.*"))
    assert not list(generator.PACKAGE_ROOT.glob("._generated.backup.*"))


def test_first_generation_boundary_failure_cleans_its_candidate(generator: ModuleType) -> None:
    def hook(current: str) -> None:
        if current == "after_temporary_to_live":
            raise OSError("injected first promotion failure")

    with pytest.raises(generator.GenerationError, match="First-generation promotion failed"):
        generator.generate(runner=FakeRunner(generator), hook=hook)
    assert not generator.LIVE_TREE.exists()
    assert not list(generator.PACKAGE_ROOT.glob("._generated.tmp.*"))


def test_rollback_failure_preserves_backup_and_temporary(generator: ModuleType) -> None:
    _seed_tree(generator, generator.LIVE_TREE, marker="previous")
    expected = _manifest(generator.LIVE_TREE)

    def hook(current: str) -> None:
        if current in {"after_live_to_backup", "before_rollback_backup_to_live"}:
            raise OSError(f"injected {current}")

    with pytest.raises(generator.GenerationError, match="rollback failed"):
        generator.generate(runner=FakeRunner(generator), hook=hook)
    backups = list(generator.PACKAGE_ROOT.glob("._generated.backup.*"))
    temporary = list(generator.PACKAGE_ROOT.glob("._generated.tmp.*"))
    assert len(backups) == 1
    assert len(temporary) == 1
    assert _manifest(backups[0]) == expected
    assert not generator.LIVE_TREE.exists()


def test_backup_cleanup_failure_preserves_valid_live_and_backup(generator: ModuleType) -> None:
    _seed_tree(generator, generator.LIVE_TREE, marker="previous")
    previous = _manifest(generator.LIVE_TREE)

    def hook(current: str) -> None:
        if current == "before_backup_cleanup":
            raise OSError("injected cleanup failure")

    with pytest.raises(generator.GenerationError, match="backup cleanup failed"):
        generator.generate(runner=FakeRunner(generator), hook=hook)
    backups = list(generator.PACKAGE_ROOT.glob("._generated.backup.*"))
    assert len(backups) == 1
    assert _manifest(backups[0]) == previous
    assert _manifest(generator.LIVE_TREE) != previous


def test_partial_backup_cleanup_failure_preserves_promoted_live(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_tree(generator, generator.LIVE_TREE, marker="previous")
    previous = _manifest(generator.LIVE_TREE)
    real_rmtree = generator.shutil.rmtree

    def partially_remove(path: str | Path, *args: object, **kwargs: object) -> None:
        candidate = Path(path)
        if candidate.name.startswith("._generated.backup."):
            (candidate / "models.py").unlink()
            raise OSError("injected partial cleanup failure")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(generator.shutil, "rmtree", partially_remove)
    with pytest.raises(generator.GenerationError, match="may be partial once cleanup starts"):
        generator.generate(runner=FakeRunner(generator))

    backups = list(generator.PACKAGE_ROOT.glob("._generated.backup.*"))
    assert len(backups) == 1
    assert not (backups[0] / "models.py").exists()
    assert _manifest(generator.LIVE_TREE) != previous
    generator.TreeValidator("0.1.0")(generator.LIVE_TREE)


def test_interruption_after_live_to_backup_converges_on_startup(generator: ModuleType) -> None:
    backup = generator.PACKAGE_ROOT / "._generated.backup.interrupted"
    temporary = generator.PACKAGE_ROOT / "._generated.tmp.candidate"
    _seed_tree(generator, backup, marker="previous")
    _seed_tree(generator, temporary, marker="candidate")
    expected = _manifest(backup)
    generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert _manifest(generator.LIVE_TREE) == expected
    assert not backup.exists()
    assert not temporary.exists()


def test_interruption_after_temporary_to_live_keeps_valid_candidate(generator: ModuleType) -> None:
    backup = generator.PACKAGE_ROOT / "._generated.backup.interrupted"
    _seed_tree(generator, backup, marker="previous")
    _seed_tree(generator, generator.LIVE_TREE, marker="candidate")
    expected = _manifest(generator.LIVE_TREE)
    generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert _manifest(generator.LIVE_TREE) == expected
    assert not backup.exists()


def test_invalid_interrupted_candidate_does_not_guess_backup_winner(generator: ModuleType) -> None:
    backup = generator.PACKAGE_ROOT / "._generated.backup.interrupted"
    temporary = generator.PACKAGE_ROOT / "._generated.tmp.abandoned"
    _seed_tree(generator, backup, marker="previous")
    _seed_tree(generator, generator.LIVE_TREE, valid=False)
    _seed_tree(generator, temporary)
    paths = [backup, generator.LIVE_TREE, temporary]
    before = {path: _manifest(path) for path in paths}
    with pytest.raises(generator.GenerationError, match="live is invalid"):
        generator._normal_state("0.1.0", generator._default_runner, generator._default_hook)
    assert {path: _manifest(path) for path in paths} == before
