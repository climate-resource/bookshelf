"""The rules for reading the two labels a book is addressed by: its name and its version.

A name is local to the bundle that registers it,
so the platform keeps it short, lower-case and free of path separators.
A version is the upstream data version rather than anything the platform mints,
so ordering it has to stay total even when the label is not SemVer at all.
"""

import re
from typing import Any

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


_LEADING_DIGITS = re.compile(r"^([0-9]+)(.*)$")
_ASCII_DIGITS = re.compile(r"^[0-9]+$")


def _identifier_key(identifier: str) -> tuple[int, int, str]:
    """Order one prerelease identifier, numeric ones ahead of alphanumeric ones."""
    if _ASCII_DIGITS.fullmatch(identifier):
        return (0, int(identifier), "")
    return (1, 0, identifier.casefold())


def version_key(version: str) -> tuple[Any, ...]:
    """Return a total SemVer-like ordering key for an upstream version label.

    SemVer decides the cases it covers:
    a prerelease sorts before the release it leads to,
    build metadata after ``+`` is not part of the order,
    and trailing zero components do not make a version newer.
    Comparison is case insensitive.

    Upstream labels are not obliged to be SemVer,
    so anything that does not parse falls back to its own casefolded text.
    That keeps the order total and deterministic for labels like ``2024-01`` or ``rev3``,
    rather than raising on them.
    """
    text = version.strip().removeprefix("v").split("+", 1)[0]
    core, _, prerelease = text.partition("-")
    identifiers = [part for part in prerelease.split(".") if part] if prerelease else []
    core_key: list[tuple[int, int, str]] = []
    for segment in core.split("."):
        match = _LEADING_DIGITS.match(segment)
        if match is None:
            core_key.append((1, 0, segment.casefold()))
            continue
        core_key.append((0, int(match.group(1)), ""))
        if match.group(2):
            identifiers.insert(0, match.group(2).lstrip("-."))

    while core_key and core_key[-1] == (0, 0, ""):
        core_key.pop()

    prerelease_key: tuple[Any, ...] = (
        (1,) if not identifiers else (0, tuple(_identifier_key(part) for part in identifiers))
    )
    return (tuple(core_key), prerelease_key)


__all__ = [
    "RESOURCE_NAME_PATTERN",
    "flatten_to_resource_name",
    "validate_resource_name",
    "version_key",
]
