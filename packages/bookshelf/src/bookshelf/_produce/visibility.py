"""The visibility argument shared by every producer registration surface."""

from __future__ import annotations

import enum

from bookshelf._generated import models
from bookshelf._records import known_member


class _Inherit(enum.Enum):
    """Sentinel distinguishing an omitted ``visibility=`` from an explicit tier."""

    INHERIT = enum.auto()

    def __repr__(self) -> str:
        # Rendered as the default in public signatures.
        return "<inherited>"


INHERIT = _Inherit.INHERIT

VisibilityInput = str | models.Visibility | _Inherit
"""A visibility argument: an explicit tier, or :data:`INHERIT` for the caller's default.

Under a recording the default is the book's tier as declared in the recipe,
so a public book records public resources and narrowing one is a deliberate act.
Everywhere else the default is ``hidden``.
"""


def resolve(
    value: VisibilityInput,
    default: models.Visibility = models.Visibility.hidden,
) -> models.Visibility:
    """Normalise a visibility input, resolving :data:`INHERIT` to ``default``."""
    if isinstance(value, _Inherit):
        return default
    return known_member(models.Visibility, value)


__all__ = ["INHERIT", "VisibilityInput", "resolve"]
