"""What a feedstock declares once: its volume, its build, and each release it can produce.

A recipe is sectioned.
``volume:`` holds the facts that are true of the dataset whichever release is being built.
``build:`` holds the facts about how it is built.
``releases:`` holds one entry per upstream version, and each entry restates itself in full.

The same content loads from either of two layouts.
Form A puts everything in one ``bookshelf.yaml``.
Form B keeps ``volume:`` and ``build:`` in ``bookshelf.yaml``
and puts one file per release under ``releases/<version>.yaml``.
The two produce an identical :class:`RecordRecipe`,
so a feedstock can move between them without changing what is recorded.

Three rules shape everything here:

- Unknown keys are an error at every level, so a typo is never silently dropped.
- A release inherits nothing from the release before it, so reading one release tells the whole story.
- The recipe names no default release, so a version is stated exactly once, on the command line.
"""

import re
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

RELEASES_DIRNAME = "releases"
_RELEASE_SUFFIXES = (".yaml", ".yml")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

_TOP_LEVEL_KEYS = ("volume", "build", RELEASES_DIRNAME)

# The keys of the removed flat form.
# Any of them at the top level means the recipe was written against the shape that no longer loads.
_REMOVED_FLAT_KEYS = ("collection", "license", "authors", "notebook", "visibility")


class _Section(BaseModel):
    """Base for every recipe section: unknown keys are rejected, and the result is immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveryFields(_Section):
    """The catalogue metadata a volume may default and any release may override.

    Every field is optional at both levels.
    A release's value wins where it is set, and the volume's applies everywhere else.
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
    source_release_date: date | None = None
    description: str | None = None
    authors: list[dict[str, Any]] | None = None


class VolumeSection(_Section):
    """The long-lived collection: what stays true across every release.

    ``name`` is the slug, and it is the one fact here that cannot change.
    ``license`` is the default every release takes unless it declares its own.
    ``topics`` and ``keywords`` are the search vocabulary,
    which is why they are declared once for the volume rather than per release.
    Letting them vary would make a filter return a different volume depending on which edition matched.
    """

    name: str = Field(min_length=1)
    license: str | None = None
    maintainers: list[dict[str, Any]] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    update_cadence: str | None = None
    deprecated: bool = False
    superseded_by: str | None = None
    deprecation_note: str | None = None
    discovery: DiscoveryFields = Field(default_factory=DiscoveryFields)


class BuildSection(_Section):
    """How the dataset is built, and the tier what it produces is published at.

    Visibility sits here rather than on the volume,
    because it is a property of what a build publishes rather than of the collection's identity.
    """

    notebook: Path | None = None
    visibility: str | None = None

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


class SourceSpec(_Section):
    """One upstream input a release is built from.

    A source is either remote or checked in, never both:

    - ``uri`` names something to fetch, and its declared ``sha256`` is what the fetch is checked
      against.
    - ``path`` names a file beside the recipe, and its digest is computed when it is read.

    ``type`` is always declared, never inferred from the file extension,
    because the extension describes the container and the type describes the content.
    Nothing in this module fetches anything. The rules here are structural.
    """

    type: str = Field(min_length=1)
    uri: str | None = None
    path: Path | None = None
    sha256: str | None = None

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
                "a source declares exactly one of uri or path. "
                "Use uri for something to fetch, or path for a file beside the recipe"
            )
        if self.uri is not None and self.sha256 is None:
            raise ValueError(
                "a uri source declares the sha256 the fetch is checked against. "
                "Add sha256, or check the file in and use path instead"
            )
        return self


class ReleaseSpec(DiscoveryFields):
    """One upstream version, stated in full.

    A release carries whichever discovery fields it overrides, its licence, and its sources.
    It inherits nothing from the release before it.
    There is no ``extends`` and no carry-forward,
    so a reader never has to walk backwards through the file to learn what a release is built from.
    """

    license: str | None = None
    sources: dict[str, SourceSpec] = Field(default_factory=dict)


class ResolvedRelease(BaseModel):
    """One release with the volume's defaults already merged in.

    This is what the recorder consumes.
    ``sequence`` is the release's position in recipe order, counting from zero,
    so a consumer can order releases without parsing a version string.
    """

    model_config = ConfigDict(frozen=True)

    version: str
    sequence: int
    license: str
    discovery: DiscoveryFields
    sources: dict[str, SourceSpec] = Field(default_factory=dict)

    @property
    def authors(self) -> tuple[dict[str, Any], ...]:
        """The people credited with this release, as the producer surfaces take them."""
        return tuple(dict(author) for author in self.discovery.authors or ())


class RecordRecipe(BaseModel):
    """A loaded recipe: one volume, one build, and the releases it can produce.

    ``releases`` keeps recipe order,
    which is the order form A's mapping states and the order form B's filenames sort into.
    """

    model_config = ConfigDict(frozen=True)

    volume: VolumeSection
    build: BuildSection = Field(default_factory=BuildSection)
    releases: dict[str, ReleaseSpec] = Field(default_factory=dict)

    @property
    def versions(self) -> tuple[str, ...]:
        """Every version this recipe defines, in recipe order."""
        return tuple(self.releases)

    def release(self, version: str) -> ResolvedRelease:
        """Resolve one release against the volume's defaults.

        This is the single place a declared value becomes an effective one,
        so a caller never merges the two levels itself.
        Raises :class:`~bookshelf._core.errors.BookshelfError` naming the available releases
        when the recipe does not define ``version``.
        """
        spec = self.releases.get(version)
        if spec is None:
            raise BookshelfError(
                f"the recipe defines no release {version!r}. {available_releases(self.versions)}"
            )
        merged = {
            name: (
                getattr(spec, name)
                if getattr(spec, name) is not None
                else getattr(self.volume.discovery, name)
            )
            for name in DiscoveryFields.model_fields
        }
        license_ = spec.license or self.volume.license
        if license_ is None:
            raise BookshelfError(
                f"release {version!r} has no licence. "
                "Set 'license:' under 'volume:' for every release, or on this release"
            )
        return ResolvedRelease(
            version=version,
            sequence=self.versions.index(version),
            license=license_,
            discovery=DiscoveryFields(**merged),
            sources=dict(spec.sources),
        )


def available_releases(versions: tuple[str, ...]) -> str:
    """Name the releases a caller can choose between, or say there are none."""
    if not versions:
        return "The recipe declares no releases. Add one under 'releases:'."
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
    return f"{at}: {error['msg'].removeprefix('Value error, ')}"


def _section[SectionT: BaseModel](
    model: type[SectionT],
    raw: Any,  # noqa: ANN401
    *,
    path: Path,
    where: str,
) -> SectionT:
    """Validate one section of a recipe, reporting every problem it has at once."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BookshelfError(f"{path} {where} must be a mapping")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        problems = ", ".join(_render(error, model=model, where=where) for error in exc.errors())
        raise BookshelfError(f"{path} {problems}") from exc


def _release_documents(path: Path, raw: dict[str, Any]) -> dict[str, Any]:
    """Collect the raw release bodies from whichever of the two layouts the feedstock uses.

    A recipe that uses both layouts is rejected rather than merged,
    because merging would make the file that states a release depend on which one loaded first.
    """
    directory = path.parent / RELEASES_DIRNAME
    declared = raw.get(RELEASES_DIRNAME)
    if directory.is_dir():
        if declared is not None:
            raise BookshelfError(
                f"{path} declares 'releases:' and {directory} also holds release files. "
                "Keep the releases in one place: drop the key, or delete the directory"
            )
        return _releases_from_directory(directory)
    if declared is None:
        return {}
    if not isinstance(declared, dict):
        raise BookshelfError(f"{path} releases must be a mapping of version to release")
    documents: dict[str, Any] = {}
    for key, body in declared.items():
        if not isinstance(key, str):
            raise BookshelfError(
                f'{path} release key {key} is a number. Quote it as "{key}", '
                "because an unquoted version is read as a YAML float "
                "and 2.70 and 2.7 would collide"
            )
        documents[key] = body
    return documents


def _releases_from_directory(directory: Path) -> dict[str, Any]:
    """Read one release per file, ordered by filename, with the file stem as the version."""
    files = sorted(
        (child for child in directory.iterdir() if child.suffix.lower() in _RELEASE_SUFFIXES),
        key=lambda child: child.name,
    )
    documents: dict[str, Any] = {}
    for child in files:
        if child.stem in documents:
            raise BookshelfError(
                f"{directory} declares release {child.stem!r} twice, once per file extension. "
                "Keep one file per release"
            )
        documents[child.stem] = yaml.safe_load(child.read_text(encoding="utf-8")) or {}
    return documents


def load_record_recipe(path: Path) -> RecordRecipe:
    """Load a sectioned recipe from ``path``, in either of its two layouts.

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
            "and declare each release under 'releases:'"
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

    recipe = RecordRecipe(
        volume=_section(VolumeSection, raw.get("volume"), path=path, where="volume"),
        build=_section(BuildSection, raw.get("build"), path=path, where="build"),
        releases={
            version: _section(ReleaseSpec, body, path=path, where=f'releases."{version}"')
            for version, body in _release_documents(path, raw).items()
        },
    )
    # Resolve every release, not just the one being built,
    # so a recipe that would fail on some other version fails now rather than on the day it is built.
    for version in recipe.versions:
        try:
            recipe.release(version)
        except BookshelfError as exc:
            raise BookshelfError(f"{path} {exc}") from exc
    return recipe


def resolve_book_visibility(
    declared: VisibilityInput | None,
    *,
    recipe: RecordRecipe | None = None,
    default: models.Visibility = models.Visibility.hidden,
) -> models.Visibility:
    """Resolve the tier a recorded book takes, which is also the default its resources take.

    The rule is: the caller, then the recipe's ``build.visibility``, then ``default``.
    ``None`` and :data:`~bookshelf._produce.visibility.INHERIT` both mean the caller said nothing.
    An empty string is invalid input to reject, never a signal to inherit the recipe's value.

    Drafting the book then makes the resolved tier the default for every resource the build
    records afterwards, so declaring the book public is enough to publish public data.
    A registration that passes its own ``visibility=`` narrows or widens that one resource.
    """
    if declared is None or declared is INHERIT:
        declared = (recipe.build.visibility if recipe is not None else None) or default
    return _visibility(declared, default)


__all__ = [
    "RELEASES_DIRNAME",
    "BuildSection",
    "DiscoveryFields",
    "RecordRecipe",
    "ReleaseSpec",
    "ResolvedRelease",
    "SourceSpec",
    "VolumeSection",
    "available_releases",
    "load_record_recipe",
    "resolve_book_visibility",
]
