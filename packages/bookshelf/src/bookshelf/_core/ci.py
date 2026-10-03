"""The one reading of ``$CI``, shared by every check for an unattended run."""

import os


def in_ci() -> bool:
    """Report whether ``$CI`` marks this process as a CI run, treating ``0`` and ``false`` as unset."""
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


__all__ = ["in_ci"]
