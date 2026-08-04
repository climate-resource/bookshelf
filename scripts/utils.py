"""Utilities for scripts"""

import tomllib
from pathlib import Path


def get_version() -> str:
    """
    Extract the current version from pyproject.toml
    """
    version = "unknown"
    # adopt path to your pyproject.toml
    pyproject_toml_file = Path(__file__).parent.parent / "pyproject.toml"

    if pyproject_toml_file.exists() and pyproject_toml_file.is_file():
        with pyproject_toml_file.open("rb") as fh:
            data = tomllib.load(fh)
        # check project.version
        if "project" in data and "version" in data["project"]:
            version = data["project"]["version"]
    return version
