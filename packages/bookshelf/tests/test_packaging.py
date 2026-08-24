"""Packaging tests for the single-namespace SDK wheel."""

import os
import subprocess
import sys
import tomllib
from email.parser import Parser
from pathlib import Path
from zipfile import ZipFile

import pytest

import bookshelf

SDK_ROOT = Path(__file__).resolve().parents[1]
SDK_VERSION = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_py_typed_marker_present() -> None:
    assert (Path(bookshelf.__file__).parent / "py.typed").is_file()


@pytest.fixture(scope="session")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the local wheel once for metadata and content inspection."""
    output = tmp_path_factory.mktemp("sdk-wheel")
    subprocess.run(
        ["uv", "build", "--project", str(SDK_ROOT), "--out-dir", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(output.glob(f"bookshelf-{SDK_VERSION}-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_wheel_metadata_uses_public_distribution_identity(wheel: Path) -> None:
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_name).decode())
        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = archive.read(entry_points_name).decode()

    assert metadata["Name"] == "bookshelf"
    assert metadata["Version"] == SDK_VERSION
    assert any(
        requirement.startswith("pyyaml>=6.0") for requirement in metadata.get_all("Requires-Dist")
    )
    assert any(
        requirement.startswith("typer>=0.12") for requirement in metadata.get_all("Requires-Dist")
    )
    assert any(
        requirement.startswith("keyring>=25") for requirement in metadata.get_all("Requires-Dist")
    )
    # The distribution keeps the ``bookshelf`` console script for the CLI.
    assert "bookshelf = bookshelf._cli:main" in entry_points


def test_wheel_declares_one_package_with_the_generated_core(wheel: Path) -> None:
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())

    required = {
        "bookshelf/__init__.py",
        "bookshelf/py.typed",
        "bookshelf/_generated/__init__.py",
        "bookshelf/_generated/models.py",
        "bookshelf/_core/oauth.py",
        "bookshelf/publisher/notebook.py",
    }
    assert required <= names
    assert not any(name.startswith("bookshelf_client/") for name in names)


def test_importing_the_sdk_does_not_require_the_git_binary() -> None:
    """Consuming a book never needs git, so the import must not depend on it.

    gitpython raises at import time when no git binary is found,
    which is why the provenance helper imports it lazily.
    A subprocess is required because gitpython is already imported in this one.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import bookshelf"],
        env={**os.environ, "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
