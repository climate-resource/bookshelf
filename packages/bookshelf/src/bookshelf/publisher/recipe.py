"""What a feedstock declares

A recipe can include:
``volume:`` holds the facts that are true of the dataset whichever version is being built.
``build:`` holds the facts about how it is built.
``versions:`` holds one entry per upstream version, and each entry restates itself in full,
including the licence it goes out under and who may read it.

Everything lives in one ``bookshelf.yaml``.

Three rules shape everything here:

- Unknown keys are an error at every level, so a typo is never silently dropped.
- A version inherits nothing from the version before it, so reading one version tells the whole story.
- The recipe names no default version, so a version is stated exactly once, on the command line.
"""

import re
from collections.abc import Collection
from datetime import date
from pathlib import Path
from typing import Any, Self, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_core import ErrorDetails

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.helpers import visibility as _visibility
from bookshelf._produce.visibility import INHERIT, VisibilityInput

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

_TOP_LEVEL_KEYS = ("volume", "build", "versions")

# The keys of the removed flat form.
# Any of them at the top level means the recipe was written against the shape that no longer loads.
_REMOVED_FLAT_KEYS = ("collection", "license", "authors", "notebook", "visibility")


class _Section(BaseModel):
    """Base for every recipe section: unknown keys are rejected, and the result is immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PersonSpec(_Section):
    """One credited person, in the shape the platform's author field takes.

    ``name`` is the only required field.
    """

    name: str = Field(min_length=1)
    email: str | None = Field(default=None, min_length=1)
    affiliation: str | None = Field(default=None, min_length=1)
    orcid: str | None = Field(default=None, min_length=1)


class DiscoveryFields(_Section):
    """The catalogue metadata a volume may default and any version may override.

    Every field is optional at both levels.
    A version's value wins where it is set, and the volume's applies everywhere else.
    Nothing here is computed from the data.
    Coverage, variables, units and frequency are derived per resource by the platform,
    so declaring them in a recipe would only let them go stale.
    """

    title: str | None = None
    abstract: str | None = None
    publisher: str | None = None
    publisher_url: str | None = None
    citation: str | None = None
    homepage_url: str | None = None
    documentation_url: str | None = None
    methodology_url: str | None = None
    repository_url: str | None = None
    release_url: str | None = None
    license_url: str | None = None
    intended_uses: str | None = None
    limitations: str | None = None
    doi: str | None = None
    release_date: date | None = None
    description: str | None = None
    authors: list[PersonSpec] | None = None


class VolumeSection(_Section):
    """The long-lived collection: what stays true across every version.

    ``name`` is the slug, and it is the one fact here that cannot change.
    ``topics`` and ``keywords`` are the search vocabulary,
    which is why they are declared once for the volume rather than per version.
    Letting them vary would make a filter return a different volume depending on which edition matched.

    A licence is not declared here.
    Each version states its own, because a relicensed version is common
    and a default here would let one be published under the wrong terms without anyone writing it down.
    """

    name: str = Field(min_length=1)
    maintainers: list[PersonSpec] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    update_cadence: str | None = None
    deprecated: bool = False
    superseded_by: str | None = None
    deprecation_note: str | None = None
    discovery: DiscoveryFields = Field(default_factory=DiscoveryFields)


class BuildSection(_Section):
    """How the dataset is built."""

    notebook: Path | None = None


class ResourceSpec(_Section):
    """One upstream input a version is built from.

    A resource is either remote or checked in, never both:

    - ``uri`` names something to fetch, and its declared ``sha256`` is what the fetch is checked
      against.
    - ``path`` names a file beside the recipe, and its digest is computed when it is read.

    ``type`` is always declared, never inferred from the file extension,
    because the extension describes the container and the type describes the content.
    Nothing in this module fetches anything. The rules here are structural.
    """

    type: str = Field(min_length=1)
    uri: str | None = Field(default=None, min_length=1)
    path: Path | None = None
    sha256: str | None = None

    @field_validator("path")
    @classmethod
    def _a_path_beside_the_recipe(cls, value: Path | None) -> Path | None:
        """Keep a path resource inside the feedstock, as a structural check rather than a lookup.

        The loader touches no filesystem, so this rejects the shapes that could never be
        checked in beside the recipe rather than asking whether the file is there.
        """
        if value is not None and (value.is_absolute() or ".." in value.parts):
            raise ValueError(
                "a path resource is relative to the recipe and stays beside it. "
                "Check the file in next to bookshelf.yaml, or use uri for something remote"
            )
        return value

    @field_validator("sha256")
    @classmethod
    def _a_sha256_digest(cls, value: str | None) -> str | None:
        if value is not None and _SHA256_RE.match(value) is None:
            raise ValueError(f"sha256 must be 64 hex characters, got {value!r}")
        return None if value is None else value.lower()

    @model_validator(mode="after")
    def _one_location_only(self) -> Self:
        if (self.uri is None) == (self.path is None):
            raise ValueError(
                "a resource declares exactly one of uri or path. "
                "Use uri for something to fetch, or path for a file beside the recipe"
            )
        if self.uri is not None and self.sha256 is None:
            raise ValueError(
                "a uri resource declares the sha256 the fetch is checked against. "
                "Add sha256, or check the file in and use path instead"
            )
        return self


class VersionSpec(DiscoveryFields):
    """One upstream version, stated in full.

    A version carries whichever discovery fields it overrides,
    its licence, its visibility, and its resources.
    It inherits nothing from the version before it.
    There is no ``extends`` and no carry-forward,
    so a reader never has to walk backwards through the file to learn what a version is built from.

    ``license`` is required, so the terms a book is published under are always stated
    next to the version they apply to.

    ``visibility`` sits here for the same reason, because who may read a version
    is a fact about that version rather than about the collection or about how it is built.
    An embargoed version alongside published ones is ordinary.
    Omitting it means ``hidden``, so the way to get it wrong is the way that shows nobody the data.
    """

    license: str = Field(min_length=1)
    visibility: str | None = None
    resources: dict[str, ResourceSpec] = Field(default_factory=dict)

    @field_validator("visibility", mode="before")
    @classmethod
    def _a_known_tier(cls, value: Any) -> Any:  # noqa: ANN401
        """Reject an unknown tier by name, rather than by pydantic's enum rendering.

        The membership test runs behind an ``isinstance`` guard,
        so an unhashable value raises this error rather than a bare ``TypeError``.
        """
        if value is None:
            return None
        if not isinstance(value, str) or value not in set(models.Visibility):
            allowed = ", ".join(sorted(models.Visibility))
            raise ValueError(f"visibility must be one of {allowed}, got {value!r}")
        return value


class ResolvedVersion(BaseModel):
    """One version with the volume's defaults already merged in.

    This is what the recorder consumes.
    ``sequence`` is the version's position in recipe order, counting from zero,
    so a consumer can order versions without parsing a version string.
    """

    model_config = ConfigDict(frozen=True)

    version: str
    sequence: int
    license: str
    visibility: str | None
    discovery: DiscoveryFields
    resources: dict[str, ResourceSpec] = Field(default_factory=dict)

    @property
    def authors(self) -> tuple[dict[str, Any], ...]:
        """The people credited with this version, as the producer surfaces take them."""
        return tuple(
            author.model_dump(exclude_none=True) for author in self.discovery.authors or ()
        )


class RecordRecipe(BaseModel):
    """A loaded recipe: one volume, one build, and the versions it can produce.

    ``versions`` keeps recipe order,
    which is the order form A's mapping states and the order form B's filenames sort into.
    """

    model_config = ConfigDict(frozen=True)

    volume: VolumeSection
    build: BuildSection = Field(default_factory=BuildSection)
    versions: dict[str, VersionSpec] = Field(default_factory=dict)

    def resolve(self, version: str) -> ResolvedVersion:
        """Resolve one version against the volume's defaults.

        This is the single place a declared value becomes an effective one,
        so a caller never merges the two levels itself.
        Raises :class:`~bookshelf._core.errors.BookshelfError` naming the available versions
        when the recipe does not define ``version``.
        """
        spec = self.versions.get(version)
        if spec is None:
            raise BookshelfError(
                f"the recipe defines no version {version!r}. {available_versions(self.versions)}"
            )
        merged = {
            name: (
                getattr(spec, name)
                if getattr(spec, name) is not None
                else getattr(self.volume.discovery, name)
            )
            for name in DiscoveryFields.model_fields
        }
        return ResolvedVersion(
            version=version,
            sequence=tuple(self.versions).index(version),
            license=spec.license,
            visibility=spec.visibility,
            discovery=DiscoveryFields(**merged),
            resources=dict(spec.resources),
        )


def available_versions(versions: Collection[str]) -> str:
    """Name the versions a caller can choose between, or say there are none."""
    if not versions:
        return "The recipe declares no versions. Add one under 'versions:'."
    listed = ", ".join(repr(version) for version in versions)
    return f"The recipe declares {listed}."


def _model_of(annotation: Any) -> type[BaseModel] | None:  # noqa: ANN401
    """Find the model an annotation carries, looking through optionals and containers."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for argument in get_args(annotation):
        found = _model_of(argument)
        if found is not None:
            return found
    return None


def _model_at(model: type[BaseModel], location: tuple[Any, ...]) -> type[BaseModel]:
    """Walk a validation error's location back to the model that rejected the key.

    The walk stops at the first element that names no field,
    which is either a mapping key or the offending key itself.
    """
    current = model
    for element in location:
        field = current.model_fields.get(str(element))
        if field is None:
            return current
        nested = _model_of(field.annotation)
        if nested is None:
            return current
        current = nested
    return current


def _render(error: ErrorDetails, *, model: type[BaseModel], where: str) -> str:
    """Render one pydantic error as a sentence that names the fix."""
    location = tuple(error["loc"])
    dotted = ".".join(str(element) for element in location)
    at = f"{where}.{dotted}" if dotted else where
    if error["type"] == "extra_forbidden":
        container = ".".join(str(element) for element in (where, *location[:-1]))
        allowed = ", ".join(_model_at(model, location).model_fields)
        return f"{at} is not a recipe key. The keys of {container} are: {allowed}"
    if error["type"] == "missing":
        return f"{at} is required"
    if error["type"] == "string_too_short":
        return f"{at} must not be empty"
    return f"{at}: {error['msg'].removeprefix('Value error, ')}"


def _section[SectionT: BaseModel](
    model: type[SectionT],
    raw: Any,  # noqa: ANN401
    *,
    path: Path,
    where: str,
) -> SectionT:
    """Validate one section of a recipe, reporting every problem it has at once.

    Several problems are listed one per line.
    Running them into a sentence would repeat a whole list of allowed keys mid-clause,
    and an author fixing two typos would have to read past the first to find the second.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BookshelfError(f"{path} {where} must be a mapping")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        problems = [_render(error, model=model, where=where) for error in exc.errors()]
        if len(problems) == 1:
            raise BookshelfError(f"{path} {problems[0]}") from exc
        listed = "\n".join(f"- {problem}" for problem in problems)
        raise BookshelfError(f"{path} has {len(problems)} problems:\n{listed}") from exc


def _version_documents(path: Path, raw: dict[str, Any]) -> dict[str, Any]:
    """Collect the raw version bodies the recipe declares, keyed by version."""
    declared = raw.get("versions")
    if declared is None:
        return {}
    if not isinstance(declared, dict):
        raise BookshelfError(f"{path} versions must be a mapping of version to its body")
    documents: dict[str, Any] = {}
    for key, body in declared.items():
        if not isinstance(key, str):
            raise BookshelfError(f"{path} {_unquoted_version_key(key)}")
        documents[key] = body
    return documents


def _unquoted_version_key(key: Any) -> str:  # noqa: ANN401
    """Name the fix for a version key YAML did not read as a string.

    A float gets the collision reasoning, because that is the case where quoting changes meaning
    rather than only type.
    Everything else names what YAML made of the key, because the author cannot see that from
    the file.
    """
    if isinstance(key, float):
        return (
            f'version key {key} is a number. Quote it as "{key}", '
            "because an unquoted version is read as a YAML float "
            "and 2.70 and 2.7 would collide"
        )
    return (
        f"version key {key} is not a string, because YAML read it as a {type(key).__name__}. "
        "Quote the key exactly as you wrote it, because a version is a string"
    )


def load_record_recipe(path: Path) -> RecordRecipe:
    """Load a sectioned recipe from ``path``.

    Every rule the recipe promises is enforced here,
    so a recipe that loads is one the recorder can run without rechecking it.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise BookshelfError(f"{path} must contain a YAML mapping")
    if any(key in raw for key in _REMOVED_FLAT_KEYS):
        raise BookshelfError(
            f"{path} uses the removed flat recipe form. "
            "Move 'collection' under 'volume: name:', 'notebook' under 'build:', "
            "and declare each version under 'versions:'"
        )
    unknown = [key for key in raw if key not in _TOP_LEVEL_KEYS]
    if unknown:
        listed = ", ".join(repr(key) for key in unknown)
        allowed = ", ".join(_TOP_LEVEL_KEYS)
        raise BookshelfError(
            f"{path} has an unknown top-level key {listed}. A recipe holds: {allowed}"
        )
    if "volume" not in raw:
        raise BookshelfError(f"{path} declares no volume. Add 'volume:' with a 'name:' under it")

    volume_raw = raw.get("volume")
    if isinstance(volume_raw, dict) and "license" in volume_raw:
        raise BookshelfError(
            f"{path} declares 'license' under 'volume:'. "
            "A licence is stated per version, so move it onto every version under 'versions:'"
        )

    build_raw = raw.get("build")
    if isinstance(build_raw, dict) and "visibility" in build_raw:
        raise BookshelfError(
            f"{path} declares 'visibility' under 'build:'. "
            "Visibility is stated per version, so move it onto every version "
            "that is not hidden under 'versions:'"
        )

    recipe = RecordRecipe(
        volume=_section(VolumeSection, volume_raw, path=path, where="volume"),
        build=_section(BuildSection, build_raw, path=path, where="build"),
        versions={
            version: _section(VersionSpec, body, path=path, where=f'versions."{version}"')
            for version, body in _version_documents(path, raw).items()
        },
    )
    return recipe


def resolve_book_visibility(
    declared: VisibilityInput | None,
    *,
    resolved: ResolvedVersion | None = None,
    default: models.Visibility = models.Visibility.hidden,
) -> models.Visibility:
    """Resolve the tier a recorded book takes, which is also the default its resources take.

    The rule is: the caller, then the version's ``visibility``, then ``default``.
    ``None`` and :data:`~bookshelf._produce.visibility.INHERIT` both mean the caller said nothing.
    An empty string is invalid input to reject, never a signal to inherit the recipe's value.

    Drafting the book then makes the resolved tier the default for every resource the build
    records afterwards, so declaring the book public is enough to publish public data.
    A registration that passes its own ``visibility=`` narrows or widens that one resource.
    """
    if declared is None or declared is INHERIT:
        declared = (resolved.visibility if resolved is not None else None) or default
    return _visibility(declared, default)


__all__ = [
    "BuildSection",
    "DiscoveryFields",
    "RecordRecipe",
    "ResolvedVersion",
    "ResourceSpec",
    "VersionSpec",
    "VolumeSection",
    "available_versions",
    "load_record_recipe",
    "resolve_book_visibility",
]
