"""The charset a resource name has to satisfy before it reaches the wire.

A name is local to the bundle that registers it,
so the platform keeps it short, lower-case and free of path separators.
Validating here turns an invalid name into an error at the call site
rather than a 422 from the register request.
"""

import re

RESOURCE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,199}$")
"""Mirrors the platform's constraint on ``RegisterResourceItem.name``."""


def validate_resource_name(value: str, *, field: str = "name") -> str:
    """Return ``value`` unchanged, or raise ``ValueError`` if it is not a usable name.

    Names carry no hierarchy.
    A producer wanting one flattens it, so ``document/build.html`` becomes ``document-build.html``.
    """
    if not value:
        raise ValueError(f"{field} must not be empty")
    if not RESOURCE_NAME_PATTERN.match(value):
        raise ValueError(
            f"{field} must start with a letter or digit and use only "
            f"lower-case letters, digits, '.', '_' or '-', "
            f"at most 200 characters (got {value!r})"
        )
    return value


def flatten_to_resource_name(value: str) -> str:
    """Return ``value`` rewritten into a valid resource name.

    Every character outside the name charset becomes ``-``,
    so ``document/build.py.ipynb`` flattens to ``document-build.py.ipynb``.
    Distinct inputs can flatten onto the same name,
    so a caller that needs them to stay distinct checks for that itself.
    """
    flattened = re.sub(r"[^a-z0-9._-]", "-", value.lower()).lstrip("-.")[:200]
    if not flattened:
        raise ValueError(f"{value!r} has no valid resource name to flatten to")
    return flattened


__all__ = ["RESOURCE_NAME_PATTERN", "flatten_to_resource_name", "validate_resource_name"]
