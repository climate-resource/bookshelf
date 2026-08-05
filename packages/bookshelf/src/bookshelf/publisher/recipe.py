"""Run-invariant framing for a recorded build, and the visibility precedence it takes part in."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.helpers import visibility as _visibility
from bookshelf._produce.visibility import INHERIT, VisibilityInput


@dataclass(frozen=True, slots=True)
class RecordRecipe:
    """Run-invariant framing for a standalone build file."""

    collection: str
    license: str
    authors: tuple[dict[str, Any], ...]
    notebook: Path | None = None
    visibility: str | None = None


def load_record_recipe(path: Path) -> RecordRecipe:
    """Load the slim run-invariant recipe used by record mode."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise BookshelfError(f"{path} must contain a YAML mapping")
    collection = raw.get("collection")
    license_value = raw.get("license")
    if not isinstance(collection, str) or not collection:
        raise BookshelfError(f"{path} must define a non-empty collection")
    if not isinstance(license_value, str) or not license_value:
        raise BookshelfError(f"{path} must define a non-empty license")
    authors_raw = raw.get("authors", [])
    if not isinstance(authors_raw, list) or not all(
        isinstance(author, dict) for author in authors_raw
    ):
        raise BookshelfError(f"{path} authors must be a list of mappings")
    notebook_raw = raw.get("notebook")
    notebook = Path(notebook_raw) if isinstance(notebook_raw, str) else None
    visibility_raw = raw.get("visibility")
    if visibility_raw is not None and (
        not isinstance(visibility_raw, str) or visibility_raw not in set(models.Visibility)
    ):
        allowed = ", ".join(sorted(models.Visibility))
        raise BookshelfError(f"{path} visibility must be one of {allowed}, got {visibility_raw!r}")
    return RecordRecipe(
        collection=collection,
        license=license_value,
        authors=tuple(dict(author) for author in authors_raw),
        notebook=notebook,
        visibility=visibility_raw,
    )


def resolve_book_visibility(
    declared: VisibilityInput | None,
    *,
    recipe: RecordRecipe | None = None,
    default: models.Visibility = models.Visibility.hidden,
) -> models.Visibility:
    """Resolve the tier a recorded book takes, which is also the default its resources take.

    The rule is: the caller, then the recipe, then ``default``.
    ``None`` and :data:`~bookshelf._produce.visibility.INHERIT` both mean the caller said nothing.
    An empty string is invalid input to reject, never a signal to inherit the recipe's value.

    Drafting the book then makes the resolved tier the default for every resource the build
    records afterwards, so declaring the book public is enough to publish public data.
    A registration that passes its own ``visibility=`` narrows or widens that one resource.
    """
    if declared is None or declared is INHERIT:
        declared = (recipe.visibility if recipe is not None else None) or default
    return _visibility(declared, default)


__all__ = [
    "RecordRecipe",
    "load_record_recipe",
    "resolve_book_visibility",
]
