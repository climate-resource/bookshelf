"""What a feedstock declares

A recipe can include:
``volume:`` holds the facts that identify the collection, whichever book is being built.
``defaults:`` holds what every book starts from, and any book may override.
``build:`` holds the facts about how it is built.
``books:`` lists the books the feedstock can produce, one per upstream version.

Everything lives in one ``bookshelf.yaml``.

The sections are named after the domain model, so a recipe reads in the same words as the
platform: a volume holds books, and a book holds resources.

Three rules shape everything here:

- Unknown keys are an error at every level, so a typo is never silently dropped.
- A book inherits from ``defaults:`` and from nowhere else,
  so reading one book and the defaults above it tells the whole story.
  No book carries anything forward from the book before it.
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
from bookshelf._produce import helpers
from bookshelf._produce.visibility import INHERIT, VisibilityInput
from bookshelf.publisher.reference import BookshelfReference, is_reference

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

_TOP_LEVEL_KEYS = ("volume", "defaults", "build", "books")

# The keys of the removed flat form.
# Any of them at the top level means the recipe was written against the shape that no longer loads.
_REMOVED_FLAT_KEYS = ("collection", "license", "authors", "notebook", "visibility")

# A key that used to sit in one section and now sits somewhere else, with the move an author makes.
# These are checked before the sections validate,
# so an upgrading feedstock is told where its key went
# rather than only that the section forbids it.
_MOVED_KEYS = (
    (
        "volume",
        "license",
        "A licence is stated per book, so move it onto every book under 'books:'",
    ),
    (
        "volume",
        "discovery",
        "Catalogue metadata is defaulted for the whole recipe, "
        "so move the fields under it straight into 'defaults:'",
    ),
    (
        "volume",
        "topics",
        "Topics are gone, because they never named a curated set "
        "and nothing distinguished one from a keyword. Use 'keywords:'",
    ),
    (
        "build",
        "visibility",
        "Visibility is a fact about a book rather than about how it is built, "
        "so move it to 'defaults:' or onto the books it applies to",
    ),
    (
        "defaults",
        "discovery",
        "The discovery fields sit flat, the same way they sit on a book, "
        "so move the fields under it up one level",
    ),
)


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
    """The catalogue metadata ``defaults:`` may state and any book may override.

    Every field is optional at both levels.
    A book's value wins where it is set, and the default applies everywhere else.
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
    """The long-lived collection: what identifies it, whichever book is being built.

    ``name`` is the slug, and it is the one fact here that cannot change.
    ``keywords`` is the search vocabulary,
    which is why it is declared once for the volume rather than per book.
    Letting it vary would make a filter return a different volume depending on which edition matched.

    Neither a licence nor catalogue metadata is declared here.
    Each book states its own licence, because a relicensed version is common
    and a default here would let one be published under the wrong terms without anyone writing it down.
    Catalogue metadata sits under ``defaults:``,
    because every field of it is a fact about a book that a volume merely supplies a starting value for.
    """

    name: str = Field(min_length=1)
    maintainers: list[PersonSpec] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    update_cadence: str | None = None
    deprecated: bool = False
    superseded_by: str | None = None
    deprecation_note: str | None = None


class BuildSection(_Section):
    """How the dataset is built."""

    notebook: Path | None = None


class _ResourceFields(_Section):
    """The fields a resource declaration carries, each one optional.

    A resource has exactly one location, and it takes one of three forms:

    - ``uri`` names something to fetch, and its declared ``sha256`` is what the fetch is checked
      against.
    - a ``uri`` under the ``bookshelf://`` scheme names data the platform already holds,
      as :class:`~bookshelf.publisher.reference.BookshelfReference` describes.
      It states no ``sha256``, because the platform is where that digest comes from.
    - ``path`` names a file beside the recipe, and its digest is computed when it is read.

    ``type`` is the same :class:`~bookshelf._generated.models.ResourceType` the resource
    registers under, so a recipe that loads cannot name a type the platform will refuse.
    It is never inferred from the file extension,
    because the extension describes the container and the type describes the content.
    A ``bookshelf://`` resource may leave it out, because it registers nothing and the
    platform already states the type. Where it is stated the resolved resource is checked
    against it.

    The rules here are structural, and nothing in this module fetches anything.
    Each stated field is checked on its own, and every field is optional.
    """

    type: models.ResourceType | None = None
    uri: str | None = Field(default=None, min_length=1)
    path: Path | None = None
    sha256: str | None = None

    @field_validator("type", mode="before")
    @classmethod
    def _a_known_resource_type(cls, value: Any) -> Any:  # noqa: ANN401
        """Reject an unknown type by name, rather than by pydantic's enum rendering.

        The membership test runs behind an ``isinstance`` guard,
        so an unhashable value raises this error rather than a bare ``TypeError``.
        """
        if value is None:
            return None
        if not isinstance(value, str) or value not in set(models.ResourceType):
            allowed = ", ".join(sorted(models.ResourceType))
            raise ValueError(f"type must be one of {allowed}, got {value!r}")
        return value

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


class ResourceDefaults(_ResourceFields):
    """A starting point for a resource of the same name, stated once under ``defaults:``.

    This is where the fields that do not move between books go, ``type`` most of all.
    It is a template and nothing more.
    A book that never names the resource does not get it,
    because a default that could add a resource to a book would make the list of things a book
    reads impossible to see from the book itself.
    """


class ResourceSpec(_ResourceFields):
    """One upstream input a book is built from, complete.

    This is what a book's declaration resolves to once its default has been merged under it,
    so the completeness rules land on the merged result rather than on either half.
    A default holding only ``type`` and a book holding only ``uri`` and ``sha256``
    are each incomplete, and together they are a resource.
    """

    @property
    def reference(self) -> BookshelfReference | None:
        """The published resource this declaration names, or ``None`` for a fetch or a file.

        Raises :class:`ValueError` where the URI takes the scheme without the coordinate,
        which is what makes reading it enough to validate it.
        """
        if self.uri is None or not is_reference(self.uri):
            return None
        return BookshelfReference.parse(self.uri)

    @model_validator(mode="after")
    def _one_complete_location(self) -> Self:
        if (self.uri is None) == (self.path is None):
            raise ValueError(
                "a resource declares exactly one of uri or path. "
                "Use uri for something to fetch, or path for a file beside the recipe"
            )
        if self.reference is not None:
            if self.sha256 is not None:
                raise ValueError(
                    "a bookshelf resource takes its digest from the platform, so it states no "
                    "sha256. Remove sha256, or name something to fetch with an http uri instead"
                )
            return self
        if self.uri is not None and self.sha256 is None:
            raise ValueError(
                "a uri resource declares the sha256 the fetch is checked against. "
                "Add sha256, or check the file in and use path instead"
            )
        if self.type is None:
            raise ValueError(
                "type is required, because a resource states the type it registers under. "
                f"It is one of: {', '.join(sorted(models.ResourceType))}"
            )
        return self


class DefaultsSection(DiscoveryFields):
    """What every book starts from.

    A book overrides any of it, and the merge is field by field rather than section by section,
    so stating one discovery field on a book keeps the rest of the defaults.

    The discovery fields sit flat here, exactly as they sit on a book,
    so the two levels of a field-by-field merge have the same shape.

    Nothing here is required.
    """

    visibility: str | None = None
    resources: dict[str, ResourceDefaults] = Field(default_factory=dict)

    @field_validator("visibility", mode="before")
    @classmethod
    def _a_known_tier(cls, value: Any) -> Any:  # noqa: ANN401
        return _a_known_visibility(value)


class BookSpec(DiscoveryFields):
    """One book the feedstock can produce, named by the upstream version it is built from.

    A book carries whichever discovery fields it overrides,
    its licence, its visibility, and the resources it reads.
    It inherits from ``defaults:`` and from nowhere else.
    There is no ``extends`` and no carry-forward from the book before it,
    so a reader never has to walk backwards through the file to learn what a book is built from.

    ``license`` is required, so the terms a book goes out under are always stated next to it.
    A default would let a relicensed book publish under the wrong terms
    without anyone having written it down.

    ``visibility`` may be defaulted, because an embargo usually covers a whole feedstock
    and a book that lifts it says so.
    Where neither states it the book is ``hidden``,
    so the way to get it wrong is the way that shows nobody the data.
    """

    version: str = Field(min_length=1)
    license: str = Field(min_length=1)
    visibility: str | None = None
    resources: dict[str, ResourceSpec] = Field(default_factory=dict)

    @field_validator("visibility", mode="before")
    @classmethod
    def _a_known_tier(cls, value: Any) -> Any:  # noqa: ANN401
        return _a_known_visibility(value)


def _a_known_visibility(value: Any) -> Any:  # noqa: ANN401
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


class ResolvedBook(BaseModel):
    """One book with the recipe's defaults already merged in.

    This is what the recorder consumes.
    ``sequence`` is the book's position in recipe order, counting from zero,
    so a consumer can order books without parsing a version string.
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
        """The people credited with this book, as the producer surfaces take them."""
        return tuple(
            author.model_dump(exclude_none=True) for author in self.discovery.authors or ()
        )


class RecordRecipe(BaseModel):
    """A loaded recipe: one volume, one set of defaults, one build, and the books it can produce.

    ``books`` keeps recipe order, which is the order the list states.
    A book's resources are already merged with their defaults by the time they land here,
    so this model holds effective resources and the loader is the only place the merge happens.
    """

    model_config = ConfigDict(frozen=True)

    volume: VolumeSection
    defaults: DefaultsSection = Field(default_factory=DefaultsSection)
    build: BuildSection = Field(default_factory=BuildSection)
    books: tuple[BookSpec, ...] = ()

    @model_validator(mode="after")
    def _one_book_per_version(self) -> Self:
        """Refuse a recipe that declares the same version twice.

        Two books claiming one version would make ``--version`` pick by position,
        which is not a choice an author ever intends to express.
        It sits on the model rather than in the loader so that ``resolve`` can trust it
        however the recipe was built.
        """
        seen: set[str] = set()
        repeated: set[str] = set()
        for book in self.books:
            if book.version in seen:
                repeated.add(book.version)
            seen.add(book.version)
        if repeated:
            listed = ", ".join(repr(version) for version in sorted(repeated))
            raise ValueError(
                f"declares more than one book for {listed}. "
                "A version names one book, so give each book its own version"
            )
        return self

    @property
    def versions(self) -> tuple[str, ...]:
        """The versions the recipe can build, in recipe order."""
        return tuple(book.version for book in self.books)

    def resolve(self, version: str) -> ResolvedBook:
        """Resolve one book against the recipe's defaults.

        This is the single place a declared value becomes an effective one,
        so a caller never merges the two levels itself.
        Raises :class:`~bookshelf._core.errors.BookshelfError` naming the available versions
        when the recipe declares no book for ``version``.
        """
        found = next(
            (
                (sequence, spec)
                for sequence, spec in enumerate(self.books)
                if spec.version == version
            ),
            None,
        )
        if found is None:
            raise BookshelfError(
                f"the recipe declares no book for version {version!r}. "
                f"{available_versions(self.versions)}"
            )
        sequence, spec = found
        merged = {
            name: (
                getattr(spec, name)
                if getattr(spec, name) is not None
                else getattr(self.defaults, name)
            )
            for name in DiscoveryFields.model_fields
        }
        return ResolvedBook(
            version=version,
            sequence=sequence,
            license=spec.license,
            visibility=spec.visibility or self.defaults.visibility,
            discovery=DiscoveryFields(**merged),
            resources=dict(spec.resources),
        )


def available_versions(versions: Collection[str]) -> str:
    """Name the versions a caller can choose between, or say there are none."""
    if not versions:
        return "The recipe declares no books. Add one under 'books:' with a 'version:'."
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


def _book_documents(path: Path, raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect the raw book bodies the recipe declares, in the order it states them."""
    declared = raw.get("books")
    if declared is None:
        return []
    if not isinstance(declared, list):
        raise BookshelfError(
            f"{path} books must be a list, one entry per book, each with a 'version:'"
        )
    documents: list[dict[str, Any]] = []
    for index, body in enumerate(declared):
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise BookshelfError(f"{path} books[{index}] must be a mapping")
        version = body.get("version")
        if version is not None and not isinstance(version, str):
            raise BookshelfError(f"{path} books[{index}] {_unquoted_version(version)}")
        documents.append(body)
    return documents


def _unquoted_version(version: Any) -> str:  # noqa: ANN401
    """Name the fix for a version YAML did not read as a string.

    A float gets the collision reasoning, because that is the case where quoting changes meaning
    rather than only type.
    Everything else names what YAML made of the value, because the author cannot see that from
    the file.
    """
    if isinstance(version, float):
        return (
            f'version {version} is a number. Quote it as "{version}", '
            "because an unquoted version is read as a YAML float "
            "and 2.70 and 2.7 would collide"
        )
    return (
        f"version {version} is not a string, because YAML read it as a {type(version).__name__}. "
        "Quote it exactly as you wrote it, because a version is a string"
    )


def _merge_resources(defaults: DefaultsSection, body: dict[str, Any]) -> Any:  # noqa: ANN401
    """Lay a book's resource declarations over the defaults of the same name.

    The merge runs on the raw mapping, before validation,
    so a resource is checked for completeness once, as the thing the recorder will read.
    Splitting ``type`` from ``uri`` across the two levels is the point of the section,
    and validating either half alone would reject both.

    A body that is not a mapping is left alone for the section validator to report,
    because a merge cannot say anything useful about it that the validator will not say better.
    """
    declared = body.get("resources")
    if not isinstance(declared, dict):
        return declared
    merged: dict[str, Any] = {}
    for name, stated in declared.items():
        default = defaults.resources.get(str(name))
        if default is None or not isinstance(stated, dict):
            merged[name] = stated
            continue
        under = default.model_dump(exclude_none=True)
        if "path" in stated or "uri" in stated:
            # A book that names its own location replaces the default's,
            # so a default uri never sits beside a book path and trips the one-location rule.
            under.pop("uri", None)
            under.pop("path", None)
            under.pop("sha256", None)
        merged[name] = {**under, **stated}
    return merged


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
            "and declare each book under 'books:'"
        )
    if "versions" in raw:
        raise BookshelfError(
            f"{path} declares 'versions:'. That section is now 'books:', "
            "a list rather than a mapping, with the version stated as 'version:' inside each entry"
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
    build_raw = raw.get("build")
    defaults_raw = raw.get("defaults")
    for section, key, advice in _MOVED_KEYS:
        body = raw.get(section)
        if isinstance(body, dict) and key in body:
            raise BookshelfError(f"{path} declares {key!r} under '{section}:'. {advice}")

    defaults = _section(DefaultsSection, defaults_raw, path=path, where="defaults")
    books = []
    for index, body in enumerate(_book_documents(path, raw)):
        version = body.get("version")
        where = f'books."{version}"' if isinstance(version, str) else f"books[{index}]"
        books.append(
            _section(
                BookSpec,
                {**body, "resources": _merge_resources(defaults, body)}
                if "resources" in body
                else body,
                path=path,
                where=where,
            )
        )
    try:
        return RecordRecipe(
            volume=_section(VolumeSection, volume_raw, path=path, where="volume"),
            defaults=defaults,
            build=_section(BuildSection, build_raw, path=path, where="build"),
            books=tuple(books),
        )
    except ValidationError as exc:
        # The whole-recipe rules live on the model, so their message arrives through pydantic
        # and gets the path prefix here, like every other refusal the loader raises.
        problem = exc.errors()[0]["msg"].removeprefix("Value error, ")
        raise BookshelfError(f"{path} {problem}") from exc


def resolve_book_visibility(
    declared: VisibilityInput | None,
    *,
    resolved: ResolvedBook | None = None,
    default: models.Visibility = models.Visibility.hidden,
) -> models.Visibility:
    """Resolve the tier a recorded book takes, which is also the default its resources take.

    The rule is: the caller, then the book's resolved ``visibility``, then ``default``.
    The book's own value and the recipe's default were already reconciled by
    :meth:`RecordRecipe.resolve`, so only one recipe-side value reaches here.
    ``None`` and :data:`~bookshelf._produce.visibility.INHERIT` both mean the caller said nothing.
    An empty string is invalid input to reject, never a signal to inherit the recipe's value.

    Drafting the book then makes the resolved tier the default for every resource the build
    records afterwards, so declaring the book public is enough to publish public data.
    A registration that passes its own ``visibility=`` narrows or widens that one resource.
    """
    if declared is None or declared is INHERIT:
        declared = (resolved.visibility if resolved is not None else None) or default
    return helpers.visibility(declared, default)


__all__ = [
    "BookSpec",
    "BuildSection",
    "DefaultsSection",
    "DiscoveryFields",
    "RecordRecipe",
    "ResolvedBook",
    "ResourceDefaults",
    "ResourceSpec",
    "VolumeSection",
    "available_versions",
    "load_record_recipe",
    "resolve_book_visibility",
]
