"""Tests for the sectioned recipe, and the framing the recorder resolves from it."""

import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.types import RegisterItem
from bookshelf._produce.visibility import INHERIT
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.recipe import (
    RecordRecipe,
    load_record_recipe,
    resolve_book_visibility,
)
from bookshelf.publisher.record import (
    _ACTIVE_RECORDING,
    _RecordingContext,
    run_record,
    setup,
)

_VERSION = "v1.0.0"

_MINIMAL = """\
volume:
  name: my-dataset
  license: MIT
  discovery:
    authors:
      - name: Ada Lovelace
        email: ada@example.com
build:
  notebook: build.py
{build_extra}
releases:
  "v1.0.0": {{}}
"""

_HEAD = """\
volume:
  name: primap-hist
  license: CC-BY-NC
  maintainers:
    - name: Jared Lewis
      email: jared@example.com
  topics: [emissions, inventories]
  keywords: [ghg, national]
  update_cadence: annual
  discovery:
    title: PRIMAP-hist
    abstract: National greenhouse gas emissions.
    publisher: Potsdam Institute for Climate Impact Research
    homepage_url: https://example.invalid/primap
    methodology_url: https://example.invalid/method
    repository_url: https://example.invalid/repo
build:
  notebook: build.py
  visibility: public
"""

# One release body per version, in the shape form B's files hold.
# Form A indents the same text under its mapping key,
# so the two layouts under test carry the same content by construction.
_RELEASES = {
    "v2.6": """\
    doi: 10.5281/zenodo.10006301
    source_release_date: 2023-09-13
    """,
    "v2.7": """\
    doi: 10.5281/zenodo.17090760
    source_release_date: 2025-08-22
    description: Adds 2023, revises the third-party gap filling.
    license: CC-BY
    publisher: Climate Resource
    release_url: https://zenodo.org/records/17090760
    authors:
      - name: Jared Lewis
        email: jared@example.com
    sources:
      raw:
        type: tabular
        uri: https://example.invalid/primap.csv
        sha256: 77834f5f16197a463fe3df7e0eb3adda62a9e48355c9481926133986e35a9019
    """,
}


def _release_body(version: str) -> str:
    """One release body, dedented, as a form B file holds it."""
    return textwrap.dedent(_RELEASES[version]).rstrip() + "\n"


def _form_a() -> str:
    """The whole recipe in one file, releases indented under their mapping keys."""
    blocks = "".join(
        f'  "{version}":\n{textwrap.indent(_release_body(version), "    ")}'
        for version in _RELEASES
    )
    return _HEAD + "releases:\n" + blocks


_FULL = _form_a()

# The recipe bookshelf-primap-hist carried against the removed flat form, verbatim.
_FLAT = """\
collection: primap-hist
license: CC-BY-NC
visibility: public
authors:
  - name: "Jared Lewis"
    email: jared.lewis@climate-resource.com
notebook: build.py
"""


def _write(tmp_path: Path, text: str) -> Path:
    """Write a recipe verbatim and return its path."""
    path = tmp_path / "bookshelf.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def _write_recipe(tmp_path: Path, build_extra: str = "") -> Path:
    """Write a minimal valid recipe, plus any extra keys under ``build:``."""
    indented = f"  {build_extra}" if build_extra else ""
    return _write(tmp_path, _MINIMAL.format(build_extra=indented))


# ----------------------------------------------------------------------
# Form A: one sectioned file.
# ----------------------------------------------------------------------
def test_a_full_recipe_populates_every_section(tmp_path: Path) -> None:
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert recipe.volume.name == "primap-hist"
    assert recipe.volume.license == "CC-BY-NC"
    assert recipe.volume.maintainers == [{"name": "Jared Lewis", "email": "jared@example.com"}]
    assert recipe.volume.topics == ["emissions", "inventories"]
    assert recipe.volume.keywords == ["ghg", "national"]
    assert recipe.volume.update_cadence == "annual"
    assert recipe.volume.discovery.title == "PRIMAP-hist"
    assert recipe.volume.discovery.repository_url == "https://example.invalid/repo"
    assert recipe.build.notebook == Path("build.py")
    assert recipe.build.visibility == "public"
    assert recipe.versions == ("v2.6", "v2.7")


def test_a_release_carries_its_declared_source(tmp_path: Path) -> None:
    release = load_record_recipe(_write(tmp_path, _FULL)).release("v2.7")

    source = release.sources["raw"]
    assert source.type == "tabular"
    assert source.uri == "https://example.invalid/primap.csv"
    assert source.sha256 == "77834f5f16197a463fe3df7e0eb3adda62a9e48355c9481926133986e35a9019"
    assert source.path is None


def test_a_release_does_not_inherit_the_previous_releases_sources(tmp_path: Path) -> None:
    """Each release restates itself, so reading one tells the whole story."""
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert recipe.release("v2.7").sources != {}
    assert recipe.release("v2.6").sources == {}


def test_a_release_licence_overrides_the_volume_default(tmp_path: Path) -> None:
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert recipe.release("v2.7").license == "CC-BY"
    assert recipe.release("v2.6").license == "CC-BY-NC"


def test_a_release_publisher_overrides_the_volume_discovery_default(tmp_path: Path) -> None:
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert recipe.release("v2.7").discovery.publisher == "Climate Resource"
    assert (
        recipe.release("v2.6").discovery.publisher
        == "Potsdam Institute for Climate Impact Research"
    )


def test_an_unstated_discovery_field_falls_through_to_the_volume(tmp_path: Path) -> None:
    release = load_record_recipe(_write(tmp_path, _FULL)).release("v2.7")

    assert release.discovery.title == "PRIMAP-hist"
    assert release.discovery.source_release_date == date(2025, 8, 22)


def test_release_order_follows_the_recipe_and_sequence_matches_it(tmp_path: Path) -> None:
    """A consumer orders releases by position, never by parsing a version string."""
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert [recipe.release(version).sequence for version in recipe.versions] == [0, 1]
    assert recipe.release("v2.6").sequence == 0


def test_an_unknown_version_names_the_releases_the_recipe_declares(tmp_path: Path) -> None:
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    with pytest.raises(BookshelfError, match=r"no release 'v9.9'.*'v2.6', 'v2.7'"):
        recipe.release("v9.9")


# ----------------------------------------------------------------------
# Form B: one file per release.
# ----------------------------------------------------------------------
def _form_b(directory: Path) -> Path:
    """The same recipe split into one file per release, ordered by filename."""
    directory.mkdir(parents=True)
    path = _write(directory, _HEAD)
    releases = directory / "releases"
    releases.mkdir()
    for version in _RELEASES:
        (releases / f"{version}.yaml").write_text(_release_body(version), encoding="utf-8")
    return path


def test_the_split_form_loads_to_the_same_recipe_as_the_single_file(tmp_path: Path) -> None:
    """The two layouts are the same content, so they must load to the same object."""
    single_directory = tmp_path / "single"
    single_directory.mkdir()

    single = load_record_recipe(_write(single_directory, _FULL))
    split = load_record_recipe(_form_b(tmp_path / "split"))

    assert single == split


def test_declaring_releases_in_both_places_is_rejected_naming_both(tmp_path: Path) -> None:
    path = _write(tmp_path, _FULL)
    (tmp_path / "releases").mkdir()
    (tmp_path / "releases" / "v2.6.yaml").write_text("doi: 10.1/a\n")

    with pytest.raises(BookshelfError, match="declares 'releases:'.*also holds release files"):
        load_record_recipe(path)


# ----------------------------------------------------------------------
# The rules the loader enforces.
# ----------------------------------------------------------------------
def test_the_removed_flat_form_is_rejected_naming_the_new_shape(tmp_path: Path) -> None:
    """The message a feedstock author sees is the whole migration guide they get."""
    path = _write(tmp_path, _FLAT)

    with pytest.raises(BookshelfError) as excinfo:
        load_record_recipe(path)

    message = str(excinfo.value)
    assert "removed flat recipe form" in message
    assert "'volume: name:'" in message
    assert "'build:'" in message
    assert "'releases:'" in message


def test_an_unquoted_numeric_release_key_is_rejected_telling_the_author_to_quote_it(
    tmp_path: Path,
) -> None:
    """An unquoted 2.70 is a YAML float, so it would collide with 2.7."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
          license: MIT
        releases:
          2.6: {}
        """,
    )

    with pytest.raises(BookshelfError) as excinfo:
        load_record_recipe(path)

    message = str(excinfo.value)
    assert 'Quote it as "2.6"' in message
    assert "2.70 and 2.7 would collide" in message


@pytest.mark.parametrize(
    ("where", "recipe"),
    [
        (
            "surplus",
            """\
            surplus: 1
            volume:
              name: my-dataset
              license: MIT
            """,
        ),
        (
            "volume.surplus",
            """\
            volume:
              name: my-dataset
              license: MIT
              surplus: 1
            """,
        ),
        (
            "volume.discovery.surplus",
            """\
            volume:
              name: my-dataset
              license: MIT
              discovery:
                surplus: 1
            """,
        ),
        (
            "build.surplus",
            """\
            volume:
              name: my-dataset
              license: MIT
            build:
              surplus: 1
            """,
        ),
        (
            'releases."v1.0".surplus',
            """\
            volume:
              name: my-dataset
              license: MIT
            releases:
              "v1.0":
                surplus: 1
            """,
        ),
        (
            'releases."v1.0".sources.raw.surplus',
            """\
            volume:
              name: my-dataset
              license: MIT
            releases:
              "v1.0":
                sources:
                  raw:
                    type: tabular
                    path: raw.csv
                    surplus: 1
            """,
        ),
    ],
)
def test_an_unknown_key_is_rejected_at_every_level(tmp_path: Path, where: str, recipe: str) -> None:
    """A typo is never silently dropped, wherever in the recipe it sits."""
    path = _write(tmp_path, recipe)

    with pytest.raises(BookshelfError) as excinfo:
        load_record_recipe(path)

    assert where in str(excinfo.value)


def _one_release(tmp_path: Path, body: str) -> Path:
    """Write a minimal recipe whose single release carries ``body``."""
    release = textwrap.indent(textwrap.dedent(body).rstrip() + "\n", "    ")
    path = tmp_path / "bookshelf.yaml"
    path.write_text(
        'volume:\n  name: my-dataset\n  license: MIT\nreleases:\n  "v1.0":\n' + release,
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("body", ["{}", "sources: {}"])
def test_a_release_without_sources_loads(tmp_path: Path, body: str) -> None:
    """A build that constructs its frame inline has no sources, and that is legal."""
    assert load_record_recipe(_one_release(tmp_path, body)).release("v1.0").sources == {}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("type: tabular\nuri: https://x.invalid/a\npath: a.csv", "exactly one"),
        ("type: tabular", "exactly one"),
        ("path: a.csv", "type is required"),
        ("type: tabular\nuri: https://x.invalid/a", "declares the sha256"),
    ],
)
def test_a_source_that_is_not_one_locatable_input_is_rejected(
    tmp_path: Path, source: str, expected: str
) -> None:
    body = "sources:\n  raw:\n" + textwrap.indent(source, "    ")
    path = _one_release(tmp_path, body)

    with pytest.raises(BookshelfError, match=expected):
        load_record_recipe(path)


def test_a_release_with_no_licence_anywhere_names_both_places_it_could_be_set(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
        releases:
          "v1.0": {}
        """,
    )

    with pytest.raises(BookshelfError, match="no licence.*under 'volume:'.*on this release"):
        load_record_recipe(path)


def test_a_recipe_with_no_volume_names_the_section_it_needs(tmp_path: Path) -> None:
    with pytest.raises(BookshelfError, match="declares no volume"):
        load_record_recipe(_write(tmp_path, "build:\n  notebook: build.py\n"))


# ----------------------------------------------------------------------
# Visibility, which the build section declares.
# ----------------------------------------------------------------------
def test_visibility_is_optional(tmp_path: Path) -> None:
    assert load_record_recipe(_write_recipe(tmp_path)).build.visibility is None


@pytest.mark.parametrize("value", ["hidden", "org", "public"])
def test_every_visibility_tier_is_accepted(tmp_path: Path, value: str) -> None:
    recipe = load_record_recipe(_write_recipe(tmp_path, f"visibility: {value}"))

    assert recipe.build.visibility == value


def test_an_unknown_visibility_is_rejected_naming_the_allowed_values(tmp_path: Path) -> None:
    path = _write_recipe(tmp_path, "visibility: everyone")

    with pytest.raises(BookshelfError, match="visibility must be one of hidden, org, public"):
        load_record_recipe(path)


@pytest.mark.parametrize("value", ["[a]", "{a: b}", "3"])
def test_a_visibility_that_is_not_a_string_stays_on_the_bookshelf_error_path(
    tmp_path: Path, value: str
) -> None:
    """An unhashable value must not escape as a raw TypeError from the membership test."""
    path = _write_recipe(tmp_path, f"visibility: {value}")

    with pytest.raises(BookshelfError, match="visibility must be one of"):
        load_record_recipe(path)


def test_direct_setup_without_a_collection_points_at_the_recorder() -> None:
    """The message names the cause and both ways forward, not just a missing argument."""
    with pytest.raises(BookshelfError) as excinfo:
        setup(version=_VERSION)

    message = str(excinfo.value)
    assert "no active recording" in message
    assert "run_record" in message
    assert "collection=" in message


def test_direct_setup_without_a_version_points_at_the_version_flag() -> None:
    """Outside a recording there is no recipe to read the version from, so it stays required."""
    with pytest.raises(BookshelfError) as excinfo:
        setup(collection="my-dataset")

    message = str(excinfo.value)
    assert "no version was passed" in message
    assert "--version" in message


@contextmanager
def _recording(recipe_path: Path, bundle_path: Path) -> Iterator[None]:
    """Enter a recording context the way run_record does, without executing a notebook."""
    recipe = load_record_recipe(recipe_path)
    context = _RecordingContext(
        recipe=recipe,
        release=recipe.release(_VERSION),
        bundle=Bundle(bundle_path),
    )
    token = _ACTIVE_RECORDING.set(context)
    try:
        yield
    finally:
        _ACTIVE_RECORDING.reset(token)
        if context.bookshelf is not None:
            context.bookshelf.close()


def test_a_recorded_build_takes_its_version_from_the_recorder(tmp_path: Path) -> None:
    """The build file names no version, so there is no second place one can be stated."""
    with _recording(_write_recipe(tmp_path), tmp_path / "bundle"):
        _, book = setup()

    assert book.metadata.version == _VERSION


def test_a_build_that_contradicts_the_recorded_version_is_rejected(tmp_path: Path) -> None:
    with (
        _recording(_write_recipe(tmp_path), tmp_path / "bundle"),
        pytest.raises(BookshelfError, match="does not match the recorded version"),
    ):
        setup(version="v9.9.9")


def test_a_build_that_repeats_the_recorded_version_is_accepted(tmp_path: Path) -> None:
    """Agreeing is not a contradiction, so an explicit repeat still records."""
    with _recording(_write_recipe(tmp_path), tmp_path / "bundle"):
        _, book = setup(version=_VERSION)

    assert book.metadata.version == _VERSION


def test_a_recorded_build_takes_its_licence_from_the_resolved_release(tmp_path: Path) -> None:
    with _recording(_write_recipe(tmp_path), tmp_path / "bundle"):
        _, book = setup()

    assert book.metadata.license == "MIT"


def test_a_recorded_build_takes_its_visibility_from_the_recipe(tmp_path: Path) -> None:
    recipe = _write_recipe(tmp_path, "visibility: public")

    with _recording(recipe, tmp_path / "bundle"):
        _, book = setup()

    assert book.metadata.visibility is models.Visibility.public


def test_an_explicit_argument_still_overrides_the_recipe(tmp_path: Path) -> None:
    recipe = _write_recipe(tmp_path, "visibility: public")

    with _recording(recipe, tmp_path / "bundle"):
        _, book = setup(visibility="org")

    assert book.metadata.visibility is models.Visibility.org


def test_an_explicit_empty_visibility_never_inherits_the_recipe(tmp_path: Path) -> None:
    """Invalid caller input must be rejected, not read as an omission.

    Falling through here would widen the book to the recipe's `public`,
    which is the one outcome this resolution must never produce by accident.
    """
    recipe = _write_recipe(tmp_path, "visibility: public")

    with _recording(recipe, tmp_path / "bundle"), pytest.raises(ValueError):
        setup(visibility="")


def test_a_recipe_that_is_silent_leaves_the_book_hidden(tmp_path: Path) -> None:
    """Neither caller nor recipe saying anything must not widen a book."""
    with _recording(_write_recipe(tmp_path), tmp_path / "bundle"):
        _, book = setup()

    assert book.metadata.visibility is models.Visibility.hidden


# ----------------------------------------------------------------------
# The book's tier is the default for the resources the build records.
# ----------------------------------------------------------------------
def test_recorded_resources_take_the_books_visibility(tmp_path: Path) -> None:
    """A public book records public resources, so a generated feedstock can publish."""
    with _recording(_write_recipe(tmp_path, "visibility: public"), tmp_path / "bundle"):
        bs, _ = setup()
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular")
            activity.register_many([RegisterItem(b"batched", type="tabular")])
            activity.register_external(type="tabular", uri="https://example.invalid/data.csv")
        bs.recording_sink.record_document(
            b"<html/>", logical_key="document/build.html", metadata={}
        )
        recorded = [r.visibility for r in bs.bundle.manifest.resources]

    assert recorded == ["public", "public", "public", "public"]


def test_a_recorded_resource_can_be_narrowed_below_the_book(tmp_path: Path) -> None:
    """Narrowing one member of a public book is a deliberate per-resource act."""
    with _recording(_write_recipe(tmp_path, "visibility: public"), tmp_path / "bundle"):
        bs, _ = setup()
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"open", type="tabular")
            activity.register(b"embargoed", type="tabular", visibility="hidden")
        recorded = [r.visibility for r in bs.bundle.manifest.resources]

    assert recorded == ["public", "hidden"]


def test_a_hidden_book_still_records_hidden_resources(tmp_path: Path) -> None:
    """The pre-existing default is unchanged when nothing declares a wider tier."""
    with _recording(_write_recipe(tmp_path), tmp_path / "bundle"):
        bs, _ = setup()
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular")
        recorded = [r.visibility for r in bs.bundle.manifest.resources]

    assert recorded == ["hidden"]


# ----------------------------------------------------------------------
# The recorder, driving a real build file.
# ----------------------------------------------------------------------
def _run(
    tmp_path: Path,
    source: str,
    *,
    version: str = _VERSION,
    parameters: dict[str, object] | None = None,
) -> Bundle:
    """Record a build file against the minimal recipe, and read back what it recorded."""
    recipe = _write_recipe(tmp_path)
    (tmp_path / "build.py").write_text(textwrap.dedent(source), encoding="utf-8")
    run_record(
        build_path=None,
        recipe_path=recipe,
        bundle_path=tmp_path / "bundle",
        version=version,
        parameters=parameters,
        cwd=tmp_path,
    )
    return Bundle.read(tmp_path / "bundle")


def test_the_recorder_hands_the_selected_version_to_the_build(tmp_path: Path) -> None:
    bundle = _run(
        tmp_path,
        """\
        import bookshelf

        bs, book = bookshelf.setup()
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular")
        """,
    )

    assert bundle.require_framing().version == _VERSION


def test_the_version_never_becomes_a_build_parameter(tmp_path: Path) -> None:
    """Seeding it as a global would reintroduce the second place a version can be stated."""
    _run(
        tmp_path,
        """\
        import bookshelf

        assert "version" not in globals(), "the version leaked into the build's globals"
        bs, book = bookshelf.setup()
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular")
        """,
    )


def test_a_build_parameter_still_reaches_the_build(tmp_path: Path) -> None:
    """``-p name=value`` is untouched, and still supersedes a top-level default."""
    _run(
        tmp_path,
        """\
        import bookshelf

        tag = "default"
        assert tag == "supplied", tag
        bs, book = bookshelf.setup()
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular")
        """,
        parameters={"tag": "supplied"},
    )


def test_the_recorder_refuses_a_version_the_recipe_does_not_define(tmp_path: Path) -> None:
    with pytest.raises(BookshelfError, match=r"no release 'v9.9'.*'v1.0.0'"):
        _run(tmp_path, "import bookshelf\n", version="v9.9")


# ----------------------------------------------------------------------
# The visibility precedence rule on its own.
# ----------------------------------------------------------------------
def _recipe(visibility: str | None) -> RecordRecipe:
    return RecordRecipe.model_validate(
        {"volume": {"name": "my-dataset", "license": "MIT"}, "build": {"visibility": visibility}}
    )


def test_the_caller_outranks_the_recipe() -> None:
    resolved = resolve_book_visibility("org", recipe=_recipe("public"))

    assert resolved is models.Visibility.org


def test_the_recipe_applies_when_the_caller_says_nothing() -> None:
    resolved = resolve_book_visibility(None, recipe=_recipe("public"))

    assert resolved is models.Visibility.public


def test_silence_everywhere_resolves_to_hidden() -> None:
    assert resolve_book_visibility(None, recipe=_recipe(None)) is models.Visibility.hidden
    assert resolve_book_visibility(None) is models.Visibility.hidden


def test_an_empty_tier_is_rejected_rather_than_read_as_an_omission() -> None:
    """The one outcome this rule must never produce by accident is a silent widening."""
    with pytest.raises(ValueError):
        resolve_book_visibility("", recipe=_recipe("public"))


def test_an_omitted_tier_on_a_direct_draft_takes_the_sinks_default() -> None:
    """Drafting without a recipe inherits whatever the sink already defaults to."""
    resolved = resolve_book_visibility(INHERIT, default=models.Visibility.org)

    assert resolved is models.Visibility.org


def test_the_recipe_is_ignored_once_a_tier_is_declared_directly() -> None:
    """A recipe reaches the rule only through setup, never through a direct draft."""
    resolved = resolve_book_visibility(models.Visibility.hidden, recipe=_recipe("public"))

    assert resolved is models.Visibility.hidden
