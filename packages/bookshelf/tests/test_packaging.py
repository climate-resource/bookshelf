"""Packaging tests for the single-namespace SDK wheel."""

from email.parser import Parser
from pathlib import Path
from zipfile import ZipFile

import pytest

import bookshelf

SDK_ROOT = Path(__file__).resolve().parents[1]


def test_py_typed_marker_present() -> None:
    assert (Path(bookshelf.__file__).parent / "py.typed").is_file()


@pytest.fixture(scope="session")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the local wheel once for metadata and content inspection."""
    import subprocess

    output = tmp_path_factory.mktemp("sdk-wheel")
    subprocess.run(
        ["uv", "build", "--project", str(SDK_ROOT), "--out-dir", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(output.glob("bookshelf-0.2.1.dev1-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_wheel_metadata_uses_unpublished_distribution_identity(wheel: Path) -> None:
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_name).decode())
        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = archive.read(entry_points_name).decode()

    assert metadata["Name"] == "bookshelf"
    assert metadata["Version"] == "0.2.1.dev1"
    assert any(
        requirement.startswith("pyyaml>=6.0") for requirement in metadata.get_all("Requires-Dist")
    )
    assert any(
        requirement.startswith("typer>=0.12") for requirement in metadata.get_all("Requires-Dist")
    )
    assert any(
        requirement.startswith("keyring>=25") for requirement in metadata.get_all("Requires-Dist")
    )
    assert "bookshelf-client" not in metadata_name
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
