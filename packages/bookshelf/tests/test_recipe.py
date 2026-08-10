"""Tests for the sectioned recipe, and the framing the recorder resolves from it."""

import re
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.types import RegisterItem
from bookshelf._produce.visibility import INHERIT
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.recipe import (
    BookSpec,
    PersonSpec,
    RecordRecipe,
    ResolvedBook,
    VolumeSection,
    load_record_recipe,
    resolve_book_visibility,
)
from bookshelf.publisher.record import (
    _ACTIVE_RECORDING,
    _RecordingContext,
    run_record,
    setup,
)
from bookshelf.publisher.reference import BookshelfReference

_VERSION = "v1.0.0"

_MINIMAL = """\
volume:
  name: my-dataset
defaults:
  authors:
    - name: Ada Lovelace
      email: ada@example.com
build:
  notebook: build.py
books:
  - version: "v1.0.0"
    license: MIT
{book_extra}"""

_HEAD = """\
volume:
  name: primap-hist
  maintainers:
    - name: Jared Lewis
      email: jared@example.com
  keywords: [ghg, national]
  update_cadence: annual
defaults:
  title: PRIMAP-hist
  abstract: National greenhouse gas emissions.
  publisher: Potsdam Institute for Climate Impact Research
  homepage_url: https://example.invalid/primap
  methodology_url: https://example.invalid/method
  repository_url: https://example.invalid/repo
  resources:
    raw:
      type: tabular
build:
  notebook: build.py
"""

# One book body per version, dedented and laid out as a list entry.
_BOOKS = {
    "v2.6": """\
    doi: 10.5281/zenodo.10006301
    release_date: 2023-09-13
    license: CC-BY-NC
    """,
    "v2.7": """\
    doi: 10.5281/zenodo.17090760
    release_date: 2025-08-22
    description: Adds 2023, revises the third-party gap filling.
    license: CC-BY
    visibility: public
    publisher: Climate Resource
    release_url: https://zenodo.org/records/17090760
    authors:
      - name: Jared Lewis
        email: jared@example.com
    resources:
      raw:
        uri: https://example.invalid/primap.csv
        sha256: 77834f5f16197a463fe3df7e0eb3adda62a9e48355c9481926133986e35a9019
    """,
}


def _book_body(version: str) -> str:
    """One book body, dedented."""
    return textwrap.dedent(_BOOKS[version]).rstrip() + "\n"


def _full_recipe() -> str:
    """The whole recipe, each book a list entry under ``books:``."""
    blocks = "".join(
        f'  - version: "{version}"\n{textwrap.indent(_book_body(version), "    ")}'
        for version in _BOOKS
    )
    return _HEAD + "books:\n" + blocks


_FULL = _full_recipe()

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


def _write_recipe(tmp_path: Path, book_extra: str = "") -> Path:
    """Write a minimal valid recipe, plus any extra keys on its single book."""
    indented = f"    {book_extra}\n" if book_extra else ""
    return _write(tmp_path, _MINIMAL.format(book_extra=indented))


def _one_book(tmp_path: Path, body: str, *, defaults: str = "") -> Path:
    """Write a minimal recipe whose single book carries ``body``."""
    book = textwrap.indent(textwrap.dedent(body).rstrip() + "\n", "    ")
    path = tmp_path / "bookshelf.yaml"
    path.write_text(
        "volume:\n  name: my-dataset\n"
        + (textwrap.dedent(defaults) if defaults else "")
        + 'books:\n  - version: "v1.0"\n    license: MIT\n'
        + book,
        encoding="utf-8",
    )
    return path


def test_a_full_recipe_populates_every_section(tmp_path: Path) -> None:
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert recipe.volume.name == "primap-hist"
    assert recipe.volume.maintainers == [PersonSpec(name="Jared Lewis", email="jared@example.com")]
    assert recipe.volume.keywords == ["ghg", "national"]
    assert recipe.volume.update_cadence == "annual"
    assert recipe.defaults.title == "PRIMAP-hist"
    assert recipe.defaults.repository_url == "https://example.invalid/repo"
    assert recipe.build.notebook == Path("build.py")
    assert recipe.versions == ("v2.6", "v2.7")


def test_a_book_carries_its_declared_resource(tmp_path: Path) -> None:
    book = load_record_recipe(_write(tmp_path, _FULL)).resolve("v2.7")

    resource = book.resources["raw"]
    assert resource.type == "tabular"
    assert resource.uri == "https://example.invalid/primap.csv"
    assert resource.sha256 == "77834f5f16197a463fe3df7e0eb3adda62a9e48355c9481926133986e35a9019"
    assert resource.path is None


def test_a_book_does_not_inherit_the_previous_books_resources(tmp_path: Path) -> None:
    """Each book restates itself, so reading one tells the whole story."""
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert recipe.resolve("v2.7").resources != {}
    assert recipe.resolve("v2.6").resources == {}


def test_each_book_carries_the_licence_it_states(tmp_path: Path) -> None:
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert recipe.resolve("v2.7").license == "CC-BY"
    assert recipe.resolve("v2.6").license == "CC-BY-NC"


def test_a_book_publisher_overrides_the_discovery_default(tmp_path: Path) -> None:
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert recipe.resolve("v2.7").discovery.publisher == "Climate Resource"
    assert (
        recipe.resolve("v2.6").discovery.publisher
        == "Potsdam Institute for Climate Impact Research"
    )


def test_an_unstated_discovery_field_falls_through_to_the_defaults(tmp_path: Path) -> None:
    book = load_record_recipe(_write(tmp_path, _FULL)).resolve("v2.7")

    assert book.discovery.title == "PRIMAP-hist"
    assert book.discovery.release_date == date(2025, 8, 22)


def test_book_order_follows_the_recipe_and_sequence_matches_it(tmp_path: Path) -> None:
    """A consumer orders books by position, never by parsing a version string."""
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert [recipe.resolve(version).sequence for version in recipe.versions] == [0, 1]
    assert recipe.resolve("v2.6").sequence == 0


def test_an_unknown_version_names_the_versions_the_recipe_declares(tmp_path: Path) -> None:
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    with pytest.raises(BookshelfError, match=r"no book for version 'v9.9'.*'v2.6', 'v2.7'"):
        recipe.resolve("v9.9")


def test_a_resource_default_supplies_the_type_the_book_leaves_out(tmp_path: Path) -> None:
    """The type does not move between books, so it is stated once."""
    book = load_record_recipe(_write(tmp_path, _FULL)).resolve("v2.7")

    assert book.resources["raw"].type is models.ResourceType.tabular


def test_a_book_overrides_a_resource_default(tmp_path: Path) -> None:
    path = _one_book(
        tmp_path,
        "resources:\n  raw:\n    type: timeseries\n    path: a.csv",
        defaults="defaults:\n  resources:\n    raw:\n      type: tabular\n",
    )

    assert load_record_recipe(path).resolve("v1.0").resources["raw"].type is (
        models.ResourceType.timeseries
    )


def test_a_book_location_replaces_the_defaults_rather_than_joining_it(tmp_path: Path) -> None:
    """A default uri beside a book path would trip the one-location rule for no reason."""
    path = _one_book(
        tmp_path,
        "resources:\n  raw:\n    path: a.csv",
        defaults=(
            "defaults:\n"
            "  resources:\n"
            "    raw:\n"
            "      type: tabular\n"
            "      uri: https://example.invalid/a.csv\n"
            "      sha256: " + "a" * 64 + "\n"
        ),
    )

    resource = load_record_recipe(path).resolve("v1.0").resources["raw"]
    assert resource.path == Path("a.csv")
    assert resource.uri is None
    assert resource.sha256 is None


def test_a_resource_default_a_book_never_names_is_not_added_to_it(tmp_path: Path) -> None:
    """A default that could add a resource would hide what a book reads from the book itself."""
    path = _one_book(
        tmp_path,
        "release_date: 2024-01-01",
        defaults="defaults:\n  resources:\n    raw:\n      type: tabular\n      path: a.csv\n",
    )

    assert load_record_recipe(path).resolve("v1.0").resources == {}


def test_a_resource_that_is_incomplete_across_both_levels_is_rejected(tmp_path: Path) -> None:
    """Completeness is asked of the merged resource, which is what the recorder reads."""
    path = _one_book(
        tmp_path,
        "resources:\n  raw: {}",
        defaults="defaults:\n  resources:\n    raw:\n      type: tabular\n",
    )

    with pytest.raises(BookshelfError, match="exactly one of uri or path"):
        load_record_recipe(path)


def test_a_default_visibility_applies_to_a_book_that_states_none(tmp_path: Path) -> None:
    """An embargo usually covers a whole feedstock, so it is stated once."""
    path = _one_book(
        tmp_path, "release_date: 2024-01-01", defaults="defaults:\n  visibility: org\n"
    )

    assert load_record_recipe(path).resolve("v1.0").visibility == "org"


def test_a_book_overrides_the_default_visibility(tmp_path: Path) -> None:
    path = _one_book(tmp_path, "visibility: public", defaults="defaults:\n  visibility: hidden\n")

    assert load_record_recipe(path).resolve("v1.0").visibility == "public"


def test_a_recipe_without_a_defaults_section_loads(tmp_path: Path) -> None:
    """The section is entirely optional, so a small feedstock never writes one."""
    recipe = load_record_recipe(
        _write(
            tmp_path,
            """\
            volume:
              name: my-dataset
            books:
              - version: "v1.0"
                license: MIT
            """,
        )
    )

    assert recipe.resolve("v1.0").visibility is None
    assert recipe.defaults.title is None


def test_an_unknown_default_visibility_is_rejected_naming_the_allowed_values(
    tmp_path: Path,
) -> None:
    path = _one_book(
        tmp_path, "release_date: 2024-01-01", defaults="defaults:\n  visibility: everyone\n"
    )

    with pytest.raises(BookshelfError, match="visibility must be one of hidden, org, public"):
        load_record_recipe(path)


def test_a_resource_default_naming_an_unknown_type_is_rejected(tmp_path: Path) -> None:
    """A default is validated where it is written, not only where it is used."""
    path = _one_book(
        tmp_path,
        "release_date: 2024-01-01",
        defaults="defaults:\n  resources:\n    raw:\n      type: csv\n",
    )

    with pytest.raises(BookshelfError, match="defaults.resources.raw.type: type must be one of"):
        load_record_recipe(path)


def test_the_removed_flat_form_is_rejected_naming_the_new_shape(tmp_path: Path) -> None:
    """The message a feedstock author sees is the whole migration guide they get."""
    path = _write(tmp_path, _FLAT)

    with pytest.raises(BookshelfError) as excinfo:
        load_record_recipe(path)

    message = str(excinfo.value)
    assert "removed flat recipe form" in message
    assert "'volume: name:'" in message
    assert "'build:'" in message
    assert "'books:'" in message


def test_the_versions_mapping_is_rejected_naming_the_list_that_replaced_it(tmp_path: Path) -> None:
    """The generic unknown-key message would not say the shape changed as well as the name."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
        versions:
          "v1.0":
            license: MIT
        """,
    )

    with pytest.raises(BookshelfError) as excinfo:
        load_record_recipe(path)

    message = str(excinfo.value)
    assert "now 'books:'" in message
    assert "a list rather than a mapping" in message
    assert "'version:' inside each entry" in message


def test_books_stated_as_a_mapping_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
        books:
          "v1.0":
            license: MIT
        """,
    )

    with pytest.raises(BookshelfError, match="books must be a list"):
        load_record_recipe(path)


def test_two_books_claiming_one_version_are_rejected(tmp_path: Path) -> None:
    """Two books claiming one version would make ``--version`` pick by position."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
        books:
          - version: "v1.0"
            license: MIT
          - version: "v1.0"
            license: CC-BY
        """,
    )

    with pytest.raises(BookshelfError, match="more than one book for 'v1.0'"):
        load_record_recipe(path)


def test_a_repeated_version_is_refused_however_the_recipe_was_built(tmp_path: Path) -> None:
    """The rule sits on the model, so building one directly cannot skip it."""
    with pytest.raises(ValidationError, match="more than one book for 'v1.0'"):
        RecordRecipe(
            volume=VolumeSection(name="my-dataset"),
            books=(
                BookSpec(version="v1.0", license="MIT"),
                BookSpec(version="v1.0", license="CC-BY"),
            ),
        )


def test_a_book_that_states_no_version_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
        books:
          - license: MIT
        """,
    )

    with pytest.raises(BookshelfError, match=re.escape("books[0].version is required")):
        load_record_recipe(path)


def test_an_unquoted_numeric_version_is_rejected_telling_the_author_to_quote_it(
    tmp_path: Path,
) -> None:
    """An unquoted 2.70 is a YAML float, so it would collide with 2.7."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
        books:
          - version: 2.6
            license: MIT
        """,
    )

    with pytest.raises(BookshelfError) as excinfo:
        load_record_recipe(path)

    message = str(excinfo.value)
    assert 'Quote it as "2.6"' in message
    assert "2.70 and 2.7 would collide" in message


@pytest.mark.parametrize(
    ("value", "read_as"),
    [("yes", "bool"), ("2025-08-22", "date"), ("2", "int")],
)
def test_a_version_that_is_not_a_string_names_what_yaml_read_it_as(
    tmp_path: Path, value: str, read_as: str
) -> None:
    """The float advice would be wrong here, so the message says what actually happened."""
    path = _write(
        tmp_path,
        f"""\
        volume:
          name: my-dataset
        books:
          - version: {value}
            license: MIT
        """,
    )

    with pytest.raises(BookshelfError) as excinfo:
        load_record_recipe(path)

    message = str(excinfo.value)
    assert f"YAML read it as a {read_as}" in message
    assert "Quote it exactly as you wrote it" in message
    assert "would collide" not in message


@pytest.mark.parametrize(
    ("where", "recipe"),
    [
        (
            "surplus",
            """\
            surplus: 1
            volume:
              name: my-dataset
            """,
        ),
        (
            "volume.surplus",
            """\
            volume:
              name: my-dataset
              surplus: 1
            """,
        ),
        (
            "defaults.authors.0.emial",
            """\
            volume:
              name: my-dataset
            defaults:
              authors:
                - name: Jared Lewis
                  emial: jared@example.com
            """,
        ),
        (
            "defaults.surplus",
            """\
            volume:
              name: my-dataset
            defaults:
              surplus: 1
            """,
        ),
        (
            "defaults.resources.raw.surplus",
            """\
            volume:
              name: my-dataset
            defaults:
              resources:
                raw:
                  type: tabular
                  surplus: 1
            """,
        ),
        (
            "volume.maintainers.0.emial",
            """\
            volume:
              name: my-dataset
              maintainers:
                - name: Jared Lewis
                  emial: jared@example.com
            """,
        ),
        (
            'books."v1.0".authors.0.surplus',
            """\
            volume:
              name: my-dataset
            books:
              - version: "v1.0"
                license: MIT
                authors:
                  - name: Jared Lewis
                    surplus: 1
            """,
        ),
        (
            "build.surplus",
            """\
            volume:
              name: my-dataset
            build:
              surplus: 1
            """,
        ),
        (
            'books."v1.0".surplus',
            """\
            volume:
              name: my-dataset
            books:
              - version: "v1.0"
                license: MIT
                surplus: 1
            """,
        ),
        (
            'books."v1.0".resources.raw.surplus',
            """\
            volume:
              name: my-dataset
            books:
              - version: "v1.0"
                license: MIT
                resources:
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


def test_two_problems_in_one_section_are_listed_one_per_line(tmp_path: Path) -> None:
    """Running them together would repeat the allowed keys mid-sentence and bury the second."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
          surplus: 1
          spare: 2
        """,
    )

    with pytest.raises(BookshelfError) as excinfo:
        load_record_recipe(path)

    lines = str(excinfo.value).splitlines()
    assert lines[0].endswith("has 2 problems:")
    assert lines[1].startswith("- volume.surplus is not a recipe key")
    assert lines[2].startswith("- volume.spare is not a recipe key")


@pytest.mark.parametrize(
    ("where", "recipe"),
    [
        (
            'books."v1.0".license',
            """\
            volume:
              name: my-dataset
            books:
              - version: "v1.0"
                license: ""
            """,
        ),
        (
            'books."v1.0".resources.raw.uri',
            """\
            volume:
              name: my-dataset
            books:
              - version: "v1.0"
                license: MIT
                resources:
                  raw:
                    type: tabular
                    uri: ""
                    sha256: 77834f5f16197a463fe3df7e0eb3adda62a9e48355c9481926133986e35a9019
            """,
        ),
    ],
)
def test_a_value_that_is_declared_but_empty_is_rejected(
    tmp_path: Path, where: str, recipe: str
) -> None:
    """Declaring a key and leaving it blank says nothing, so it is a mistake rather than silence."""
    path = _write(tmp_path, recipe)

    with pytest.raises(BookshelfError, match=f"{re.escape(where)} must not be empty"):
        load_record_recipe(path)


@pytest.mark.parametrize("value", ["/etc/passwd", "../outside/raw.csv", "nested/../../raw.csv"])
def test_a_path_resource_that_leaves_the_feedstock_is_rejected(tmp_path: Path, value: str) -> None:
    """The check is structural, because the loader touches no filesystem."""
    path = _one_book(tmp_path, f"resources:\n  raw:\n    type: tabular\n    path: {value}")

    with pytest.raises(BookshelfError, match="is relative to the recipe and stays beside it"):
        load_record_recipe(path)


def test_a_path_resource_may_sit_in_a_subdirectory_of_the_feedstock(tmp_path: Path) -> None:
    path = _one_book(tmp_path, "resources:\n  raw:\n    type: tabular\n    path: data/raw.csv")

    assert load_record_recipe(path).resolve("v1.0").resources["raw"].path == Path("data/raw.csv")


def test_a_bookshelf_resource_states_neither_a_digest_nor_a_type(tmp_path: Path) -> None:
    """Both are facts the platform already holds, so a recipe restating them could go stale."""
    path = _one_book(
        tmp_path, "resources:\n  raw:\n    uri: bookshelf://primap-hist/v2.7_e002/by_country"
    )

    spec = load_record_recipe(path).resolve("v1.0").resources["raw"]

    assert spec.type is None
    assert spec.reference == BookshelfReference(
        volume="primap-hist", version="v2.7", edition=2, name_in_book="by_country"
    )


def test_a_resource_that_is_fetched_carries_no_reference(tmp_path: Path) -> None:
    body = f"resources:\n  raw:\n    type: tabular\n    uri: https://x.invalid/a\n    sha256: {'a' * 64}"

    assert (
        load_record_recipe(_one_book(tmp_path, body)).resolve("v1.0").resources["raw"].reference
        is None
    )


def test_a_bookshelf_resource_that_states_a_digest_is_rejected(tmp_path: Path) -> None:
    body = (
        "resources:\n  raw:\n"
        "    uri: bookshelf://primap-hist/v2.7_e002/by_country\n"
        f"    sha256: {'a' * 64}"
    )

    with pytest.raises(BookshelfError, match="takes its digest from the platform"):
        load_record_recipe(_one_book(tmp_path, body))


def test_a_bookshelf_resource_that_is_not_a_coordinate_is_rejected(tmp_path: Path) -> None:
    path = _one_book(tmp_path, "resources:\n  raw:\n    uri: bookshelf://primap-hist")

    with pytest.raises(BookshelfError, match="is not a bookshelf reference"):
        load_record_recipe(path)


def test_a_bookshelf_resource_may_still_state_the_type_it_expects(tmp_path: Path) -> None:
    """A default naming the type for a whole feedstock reaches a bookshelf resource too."""
    path = _one_book(
        tmp_path,
        "resources:\n  raw:\n    uri: bookshelf://primap-hist/v2.7_e002/by_country",
        defaults="defaults:\n  resources:\n    raw:\n      type: timeseries\n",
    )

    assert load_record_recipe(path).resolve("v1.0").resources["raw"].type == (
        models.ResourceType.timeseries
    )


@pytest.mark.parametrize("body", ["release_date: 2024-01-01", "resources: {}"])
def test_a_book_without_resources_loads(tmp_path: Path, body: str) -> None:
    """A build that constructs its frame inline has no resources, and that is legal."""
    assert load_record_recipe(_one_book(tmp_path, body)).resolve("v1.0").resources == {}


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ("type: tabular\nuri: https://x.invalid/a\npath: a.csv", "exactly one"),
        ("type: tabular", "exactly one"),
        ("path: a.csv", "type is required"),
        ("type: tabular\nuri: https://x.invalid/a", "declares the sha256"),
    ],
)
def test_a_resource_that_is_not_one_locatable_input_is_rejected(
    tmp_path: Path, resource: str, expected: str
) -> None:
    body = "resources:\n  raw:\n" + textwrap.indent(resource, "    ")
    path = _one_book(tmp_path, body)

    with pytest.raises(BookshelfError, match=expected):
        load_record_recipe(path)


def test_a_resource_type_the_platform_does_not_register_is_rejected(tmp_path: Path) -> None:
    """A recipe that loads cannot name a type the platform would refuse at registration."""
    path = _one_book(tmp_path, "resources:\n  raw:\n    type: csv\n    path: a.csv")

    with pytest.raises(
        BookshelfError,
        match="type must be one of binary, document, geospatial, tabular, timeseries",
    ):
        load_record_recipe(path)


@pytest.mark.parametrize("value", ["[a]", "{a: b}", "3"])
def test_a_resource_type_that_is_not_a_string_stays_on_the_bookshelf_error_path(
    tmp_path: Path, value: str
) -> None:
    """An unhashable value must not escape as a raw TypeError from the membership test."""
    path = _one_book(tmp_path, f"resources:\n  raw:\n    type: {value}\n    path: a.csv")

    with pytest.raises(BookshelfError, match="type must be one of"):
        load_record_recipe(path)


def test_a_resolved_resource_carries_the_type_as_the_platform_enum(tmp_path: Path) -> None:
    path = _one_book(tmp_path, "resources:\n  raw:\n    type: tabular\n    path: a.csv")

    resource = load_record_recipe(path).resolve("v1.0").resources["raw"]

    assert resource.type is models.ResourceType.tabular


def test_a_book_that_states_no_licence_is_rejected(tmp_path: Path) -> None:
    """The terms a book is published under are never inferred."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
        books:
          - version: "v1.0"
        """,
    )

    with pytest.raises(BookshelfError, match='books."v1.0".license is required'):
        load_record_recipe(path)


def test_a_licence_under_the_volume_is_rejected_naming_where_it_moved(tmp_path: Path) -> None:
    """The volume-level default is gone, so the message says what to do rather than only refusing."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
          license: MIT
        books:
          - version: "v1.0"
            license: MIT
        """,
    )

    with pytest.raises(BookshelfError, match="move it onto every book"):
        load_record_recipe(path)


def test_discovery_under_the_volume_is_rejected_naming_where_it_moved(tmp_path: Path) -> None:
    """The section moved, so the generic unknown-key message would not name the fix."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
          discovery:
            title: My dataset
        books:
          - version: "v1.0"
            license: MIT
        """,
    )

    with pytest.raises(BookshelfError, match="move the fields under it straight into 'defaults:'"):
        load_record_recipe(path)


def test_a_discovery_block_under_defaults_is_rejected_naming_the_flat_shape(
    tmp_path: Path,
) -> None:
    """The fields sit flat, so the nesting that once held them names its own fix."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
        defaults:
          discovery:
            title: My dataset
        books:
          - version: "v1.0"
            license: MIT
        """,
    )

    with pytest.raises(BookshelfError, match="move the fields under it up one level"):
        load_record_recipe(path)


def test_a_discovery_field_sits_flat_under_defaults(tmp_path: Path) -> None:
    """Defaults and a book carry the same field set, which is what the merge wants."""
    path = _one_book(
        tmp_path, "release_date: 2024-01-01", defaults="defaults:\n  title: My dataset\n"
    )

    assert load_record_recipe(path).resolve("v1.0").discovery.title == "My dataset"


def test_topics_under_the_volume_are_rejected_naming_keywords(tmp_path: Path) -> None:
    """Nothing distinguished a topic from a keyword, so only keywords remain."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
          topics: [emissions]
        books:
          - version: "v1.0"
            license: MIT
        """,
    )

    with pytest.raises(BookshelfError, match="Topics are gone.*Use 'keywords:'"):
        load_record_recipe(path)


def test_a_recipe_with_no_volume_names_the_section_it_needs(tmp_path: Path) -> None:
    with pytest.raises(BookshelfError, match="declares no volume"):
        load_record_recipe(_write(tmp_path, "build:\n  notebook: build.py\n"))


def test_visibility_is_optional(tmp_path: Path) -> None:
    assert load_record_recipe(_write_recipe(tmp_path)).resolve(_VERSION).visibility is None


@pytest.mark.parametrize("value", ["hidden", "org", "public"])
def test_every_visibility_tier_is_accepted(tmp_path: Path, value: str) -> None:
    recipe = load_record_recipe(_write_recipe(tmp_path, f"visibility: {value}"))

    assert recipe.resolve(_VERSION).visibility == value


def test_one_book_can_be_embargoed_while_another_is_public(tmp_path: Path) -> None:
    """The case build-level visibility could not express without editing the recipe twice."""
    recipe = load_record_recipe(_write(tmp_path, _FULL))

    assert recipe.resolve("v2.7").visibility == "public"
    assert recipe.resolve("v2.6").visibility is None


def test_visibility_under_build_names_where_it_moved_to(tmp_path: Path) -> None:
    """The generic unknown-key message would only list the keys of ``build:``."""
    path = _write(
        tmp_path,
        """\
        volume:
          name: my-dataset
        build:
          notebook: build.py
          visibility: public
        books:
          - version: "v1.0.0"
            license: MIT
        """,
    )

    with pytest.raises(BookshelfError, match="move it to 'defaults:' or onto the books"):
        load_record_recipe(path)


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
        resolved=recipe.resolve(_VERSION),
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
        book = setup().book

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
        book = setup(version=_VERSION).book

    assert book.metadata.version == _VERSION


def test_a_recorded_build_takes_its_licence_from_the_resolved_book(tmp_path: Path) -> None:
    with _recording(_write_recipe(tmp_path), tmp_path / "bundle"):
        book = setup().book

    assert book.metadata.license == "MIT"


def test_a_recorded_build_takes_its_visibility_from_the_recipe(tmp_path: Path) -> None:
    recipe = _write_recipe(tmp_path, "visibility: public")

    with _recording(recipe, tmp_path / "bundle"):
        book = setup().book

    assert book.metadata.visibility is models.Visibility.public


def test_an_explicit_argument_still_overrides_the_recipe(tmp_path: Path) -> None:
    recipe = _write_recipe(tmp_path, "visibility: public")

    with _recording(recipe, tmp_path / "bundle"):
        book = setup(visibility="org").book

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
        book = setup().book

    assert book.metadata.visibility is models.Visibility.hidden


def test_recorded_resources_take_the_books_visibility(tmp_path: Path) -> None:
    """A public book records public resources, so a generated feedstock can publish."""
    with _recording(_write_recipe(tmp_path, "visibility: public"), tmp_path / "bundle"):
        bs = setup().bs
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
        bs = setup().bs
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"open", type="tabular")
            activity.register(b"embargoed", type="tabular", visibility="hidden")
        recorded = [r.visibility for r in bs.bundle.manifest.resources]

    assert recorded == ["public", "hidden"]


def test_a_hidden_book_still_records_hidden_resources(tmp_path: Path) -> None:
    """The pre-existing default is unchanged when nothing declares a wider tier."""
    with _recording(_write_recipe(tmp_path), tmp_path / "bundle"):
        bs = setup().bs
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular")
        recorded = [r.visibility for r in bs.bundle.manifest.resources]

    assert recorded == ["hidden"]


def _run(
    tmp_path: Path,
    resource: str,
    *,
    version: str = _VERSION,
    parameters: dict[str, object] | None = None,
) -> Bundle:
    """Record a build file against the minimal recipe, and read back what it recorded."""
    recipe = _write_recipe(tmp_path)
    (tmp_path / "build.py").write_text(textwrap.dedent(resource), encoding="utf-8")
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

        build = bookshelf.setup()
        with build.bs.activity(kind="build", code_ref="test") as activity:
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
        build = bookshelf.setup()
        with build.bs.activity(kind="build", code_ref="test") as activity:
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
        build = bookshelf.setup()
        with build.bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular")
        """,
        parameters={"tag": "supplied"},
    )


def test_the_recorder_refuses_a_version_the_recipe_does_not_define(tmp_path: Path) -> None:
    with pytest.raises(BookshelfError, match=r"no book for version 'v9.9'.*'v1.0.0'"):
        _run(tmp_path, "import bookshelf\n", version="v9.9")


def _resolved(visibility: str | None) -> ResolvedBook:
    return RecordRecipe.model_validate(
        {
            "volume": {"name": "my-dataset"},
            "books": [{"version": _VERSION, "license": "MIT", "visibility": visibility}],
        }
    ).resolve(_VERSION)


def test_the_caller_outranks_the_book() -> None:
    resolved = resolve_book_visibility("org", resolved=_resolved("public"))

    assert resolved is models.Visibility.org


def test_the_book_applies_when_the_caller_says_nothing() -> None:
    resolved = resolve_book_visibility(None, resolved=_resolved("public"))

    assert resolved is models.Visibility.public


def test_silence_everywhere_resolves_to_hidden() -> None:
    assert resolve_book_visibility(None, resolved=_resolved(None)) is models.Visibility.hidden
    assert resolve_book_visibility(None) is models.Visibility.hidden


def test_an_empty_tier_is_rejected_rather_than_read_as_an_omission() -> None:
    """The one outcome this rule must never produce by accident is a silent widening."""
    with pytest.raises(ValueError):
        resolve_book_visibility("", resolved=_resolved("public"))


def test_an_omitted_tier_on_a_direct_draft_takes_the_sinks_default() -> None:
    """Drafting without a recipe inherits whatever the sink already defaults to."""
    resolved = resolve_book_visibility(INHERIT, default=models.Visibility.org)

    assert resolved is models.Visibility.org


def test_the_book_is_ignored_once_a_tier_is_declared_directly() -> None:
    """A recipe reaches the rule only through setup, never through a direct draft."""
    resolved = resolve_book_visibility(models.Visibility.hidden, resolved=_resolved("public"))

    assert resolved is models.Visibility.hidden
