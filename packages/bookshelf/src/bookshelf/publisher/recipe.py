"""Pydantic models for ``bookshelf.yaml``: the mutable recipe artifact.

The recipe file declares *intent*: which collection (Volume) to publish to,
what inputs exist and how to fetch them,
what the activity looks like,
and what outputs to register.
At publish time the recipe is *compiled* into an immutable ``bookshelf.lock``
(see ``lock.py``).

Recipe authors never supply ``code_ref``, ``config_hash``, or ``runner`` :
those are auto-derived at build time and rejected if found in the authored YAML.
"""

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bookshelf.publisher._models import Author

ResourceType = Literal["timeseries", "geospatial", "tabular", "document", "binary"]
Visibility = Literal["hidden", "org", "public"]
InputMode = Literal["managed", "pointer"]

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _validate_sha256(value: str) -> str:
    """Reject any string that is not a valid ``sha256:<hex>`` digest."""
    if not _SHA256_RE.match(value):
        raise ValueError(f"sha256 must be in the form 'sha256:<64 hex digits>', got {value!r}")
    return value


# Recipe authors reuse the volume ``Author`` model.
# The fields and ``extra="forbid"`` contract therefore stay identical.
RecipeAuthor = Author


class InputSpec(BaseModel):
    """One raw input declared in a recipe book section.

    ``mode`` governs ingest policy:
    - ``managed`` (default): fetch the bytes, verify ``sha256``,
      and re-host them content-addressed on the platform,
      registering the managed resource with ``original_url`` as provenance metadata.
    - ``pointer``: do *not* fetch, register an external-pointer ``Resource``
      carrying ``external_uri`` + ``sha256`` (use when the licence forbids
      re-hosting).

    The ``sha256`` field is a **fetch-time assertion** for managed inputs :
    the download is rejected if the bytes do not match.
    For pointer inputs it is the declared hash of the remote file.
    Either way it must be in ``sha256:<64 hex digits>`` format.
    """

    model_config = ConfigDict(extra="forbid")

    mode: InputMode = "managed"
    url: str
    sha256: str
    type: ResourceType

    @field_validator("sha256")
    @classmethod
    def _check_sha256(cls, v: str) -> str:
        return _validate_sha256(v)


class OutputSpec(BaseModel):
    """One output artifact produced by this book's activity.

    ``used`` lists the *logical names* of recipe inputs
    that this output depends on.
    Every name in ``used`` must resolve to a key
    in the parent book's ``inputs`` mapping.
    Validation happens at the ``RecipeBook`` level,
    where the full ``inputs`` mapping is visible.
    """

    model_config = ConfigDict(extra="forbid")

    path: Path
    type: ResourceType
    name_in_book: str
    used: list[str] = Field(default_factory=list)


# Keys that must never appear in the authored activity block.
_FORBIDDEN_ACTIVITY_KEYS = frozenset({"code_ref", "config_hash", "runner"})


class ActivitySpec(BaseModel):
    """The activity block authored in a recipe book section.

    Only ``kind`` and ``params`` are authored.
    ``code_ref``, ``config_hash``, and ``runner`` are auto-derived at build
    time and are **rejected** if the author includes them.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "process"
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _reject_auto_derived_keys(cls, data: Any) -> Any:
        """Fail fast when an author includes auto-derived keys."""
        if not isinstance(data, dict):
            return data
        bad = _FORBIDDEN_ACTIVITY_KEYS & data.keys()
        if bad:
            raise ValueError(
                f"Activity keys {sorted(bad)} are auto-derived at build time "
                "and must not be authored in bookshelf.yaml"
            )
        return data


class RecipeBook(BaseModel):
    """One versioned book inside the recipe.

    ``inputs`` is a mapping from logical names (used in lineage references)
    to :class:`InputSpec` entries.
    ``outputs`` is a mapping from logical names to :class:`OutputSpec` entries.
    Every ``output.used`` element must name a key that appears in ``inputs``.
    """

    model_config = ConfigDict(extra="forbid")

    version: str
    license: str | None = None
    visibility: Visibility = "hidden"
    description: str | None = None
    notebook: Path | None = None

    inputs: dict[str, InputSpec] = Field(default_factory=dict)
    activity: ActivitySpec = Field(default_factory=ActivitySpec)
    outputs: dict[str, OutputSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_used_refs(self) -> "RecipeBook":
        """Every ``output.used`` ref must resolve to a declared input name."""
        for out_name, out_spec in self.outputs.items():
            for ref in out_spec.used:
                if ref not in self.inputs:
                    declared = sorted(self.inputs.keys())
                    raise ValueError(
                        f"Output {out_name!r} references undeclared input {ref!r}, "
                        f"declared inputs: {declared}"
                    )
        return self


class Recipe(BaseModel):
    """The parsed and validated ``bookshelf.yaml`` recipe.

    ``collection`` maps to the target Volume name.
    ``license`` is the collection-level default SPDX identifier.
    Individual ``books[].license`` values override it per version.
    ``books`` must be non-empty.
    """

    model_config = ConfigDict(extra="forbid")

    collection: str
    license: str
    authors: list[RecipeAuthor] = Field(default_factory=list)
    books: Annotated[list[RecipeBook], Field(min_length=1)]


def load_recipe(path: Path) -> Recipe:
    """Load and validate a ``bookshelf.yaml`` recipe file.

    Returns a fully-validated :class:`Recipe` instance.
    Raises :class:`ValueError` (wrapping pydantic ``ValidationError``)
    with a human-readable message on any schema problem.
    """
    try:
        with path.open("rb") as fh:
            raw = yaml.safe_load(fh)
    except OSError as exc:
        raise ValueError(f"Cannot read recipe file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Recipe file {path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"Recipe must be a YAML mapping, got {type(raw).__name__!r}")

    try:
        return Recipe.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"Invalid recipe in {path}:\n{exc}") from exc


__all__ = [
    "ActivitySpec",
    "InputMode",
    "InputSpec",
    "OutputSpec",
    "Recipe",
    "RecipeAuthor",
    "RecipeBook",
    "ResourceType",
    "Visibility",
    "load_recipe",
]
