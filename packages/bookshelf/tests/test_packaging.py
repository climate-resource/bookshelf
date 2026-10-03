"""Packaging tests for the single-namespace SDK wheel."""

import os
import subprocess
import sys
import tarfile
import tomllib
from email.parser import Parser
from pathlib import Path
from zipfile import ZipFile

import pytest

import bookshelf

SDK_ROOT = Path(__file__).resolve().parents[1]
SDK_VERSION = tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_version_matches_the_distribution() -> None:
    assert bookshelf.__version__ == SDK_VERSION


def test_py_typed_marker_present() -> None:
    assert (Path(bookshelf.__file__).parent / "py.typed").is_file()


@pytest.fixture(scope="session")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the local sdist and wheel once for metadata and content inspection."""
    output = tmp_path_factory.mktemp("sdk-dist")
    subprocess.run(
        ["uv", "build", "--project", str(SDK_ROOT), "--out-dir", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    return output


@pytest.fixture(scope="session")
def wheel(dist: Path) -> Path:
    wheels = list(dist.glob(f"bookshelf-{SDK_VERSION}-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.fixture(scope="session")
def sdist(dist: Path) -> Path:
    return dist / f"bookshelf-{SDK_VERSION}.tar.gz"


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
        requirement.startswith("typer>=0.26") for requirement in metadata.get_all("Requires-Dist")
    )
    assert metadata["License-Expression"] == "MIT"
    assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
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


def test_sdist_ships_the_licence_but_not_the_tests(sdist: Path) -> None:
    with tarfile.open(sdist) as archive:
        names = {name.split("/", 1)[1] for name in archive.getnames() if "/" in name}

    assert {"LICENSE", "src/bookshelf/py.typed", "src/bookshelf/__init__.py"} <= names
    assert not any(name.startswith(("tests/", "scripts/")) for name in names)


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


def test_the_root_package_exports_typed_errors_and_deployments() -> None:
    from bookshelf._core import config, errors

    assert bookshelf.NotFoundError is errors.NotFoundError
    assert issubclass(bookshelf.ConflictError, bookshelf.APIError)
    assert bookshelf.STAGING_API_URL == config.STAGING_API_URL
    assert bookshelf.PRODUCTION_API_URL == config.PRODUCTION_API_URL


def test_every_sdk_error_is_exported_from_the_root_package() -> None:
    import bookshelf.publisher  # noqa: F401

    def subclasses(cls: type) -> set[type]:
        found = set(cls.__subclasses__())
        return found.union(*(subclasses(sub) for sub in found))

    public = {
        error
        for error in subclasses(bookshelf.BookshelfError)
        if error.__module__.startswith("bookshelf.")
        and not error.__module__.startswith("bookshelf._cli")
        and not error.__name__.startswith("_")
    }

    assert {error.__name__ for error in public} <= set(bookshelf.__all__)
    assert all(getattr(bookshelf, error.__name__) is error for error in public)
