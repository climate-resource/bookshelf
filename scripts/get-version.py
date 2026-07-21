"""
Extract the current version from pyproject.toml and print to stdout

These can then be used in our release template and documentation building.
"""

from scripts.utils import get_version

if __name__ == "__main__":
    print(get_version())
