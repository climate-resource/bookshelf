"""Set the release version in GITHUB_ENV"""

import os

from utils import get_version


def main():
    """
    Extract the current version from pyproject.toml and write to GITHUB_ENV

    Only the major and minor version are written to GITHUB_ENV
    """
    version = get_version()
    if version == "unknown":
        raise ValueError("Version not found")

    parts = version.split(".")

    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as f:
        f.write(f"DOCS_VERSION={parts[0]}.{parts[1]}\n")


if __name__ == "__main__":
    main()
