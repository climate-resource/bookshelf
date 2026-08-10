"""The charset a resource name has to satisfy.

A name is local to the bundle that registers it,
so the platform keeps it short, lower-case and free of path separators.
"""

import re

_NAME_CHARS = "a-z0-9._-"
_MAX_NAME_LENGTH = 200

RESOURCE_NAME_PATTERN = re.compile(rf"^[a-z0-9][{_NAME_CHARS}]{{0,{_MAX_NAME_LENGTH - 1}}}$")
"""Mirrors the platform's constraint on ``RegisterResourceItem.name``."""

_OUTSIDE_NAME_CHARS = re.compile(rf"[^{_NAME_CHARS}]")


def validate_resource_name(value: str) -> str:
    """Return ``value`` unchanged, or raise ``ValueError`` if it is not a usable name."""
    if not RESOURCE_NAME_PATTERN.match(value):
        raise ValueError(
            "name must start with a letter or digit and use only "
            "lower-case letters, digits, '.', '_' or '-', "
            f"at most {_MAX_NAME_LENGTH} characters (got {value!r})"
        )
    return value


def flatten_to_resource_name(value: str) -> str:
    """Return ``value`` rewritten into a valid resource name.

    Every character outside the name charset becomes ``-``,
    so ``document/build.py.ipynb`` flattens to ``document-build.py.ipynb``.
    A name has to open on a letter or digit, so any leading punctuation is dropped.
    Distinct inputs can flatten onto the same name,
    so a caller that needs them to stay distinct checks for that itself.
    """
    flattened = _OUTSIDE_NAME_CHARS.sub("-", value.lower()).lstrip("-._")[:_MAX_NAME_LENGTH]
    if not flattened:
        raise ValueError(f"{value!r} has no valid resource name to flatten to")
    return validate_resource_name(flattened)


__all__ = ["RESOURCE_NAME_PATTERN", "flatten_to_resource_name", "validate_resource_name"]
