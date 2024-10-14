"""Utilities for scripts"""

from pathlib import Path

import toml


def get_version() -> str:
    """
    Extract the current version from pyproject.toml
    """
    version = "unknown"
    # adopt path to your pyproject.toml
    pyproject_toml_file = Path(__file__).parent.parent / "pyproject.toml"

    if pyproject_toml_file.exists() and pyproject_toml_file.is_file():
        data = toml.load(pyproject_toml_file)
        # check project.version
        if "project" in data and "version" in data["project"]:
            version = data["project"]["version"]
    return version
