"""A resource carries its own catalogue metadata, from both ends of the produce path.

The property under test is that attribution is per resource and never inherited.
A book's authors credit whoever assembled the book,
which is a different claim from who made any one resource inside it.
"""

import textwrap
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf.cache import ContentCache
from bookshelf.publisher import recording as recording_module
from bookshelf.publisher.bundle import Bundle, BundleResource
from bookshelf.publisher.recipe import load_record_recipe
from bookshelf.publisher.record import run_record
from bookshelf.publisher.recording import RecordingSink
from bookshelf.publisher.replay import replay_bundle_sync
from tests._replay import replay_client, replayed

_RECIPE = """\
volume:
  name: my-dataset
build:
  notebook: build.py
books:
  - version: "v1.0.0"
    license: CC-BY-4.0
    authors:
      - name: Climate Resource
    resources:
      raw:
        type: tabular
        path: inputs/raw.csv
        description: Somebody else's workbook.
        authors:
          - name: Upstream Modelling Team
            affiliation: Not us
        license: CC-BY-SA-4.0
        license_url: https://creativecommons.org/licenses/by-sa/4.0/
        doi: 10.5281/zenodo.1
        citation: Upstream Modelling Team (2024).
        tags:
          - upstream
"""

_BUILD = """\
import bookshelf

bs, book = bookshelf.setup()
raw = bs.use("raw")
book.write(
    "totals",
    raw.path.read_bytes(),
    used=[raw],
    description="What we made from it.",
    authors=[{"name": "Climate Resource"}],
    license="CC-BY-4.0",
    tags=["derived"],
)
book.publish()
"""


@pytest.fixture(autouse=True)
def _pinned_code_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """The recorder runs from a scratch directory, which is no clone to read a code ref from."""
    monkeypatch.setattr(
        recording_module, "derive_code_ref", lambda: "https://example.invalid/test@0"
    )


def _record(tmp_path: Path, recipe: str = _RECIPE, build: str = _BUILD) -> Bundle:
    """Record the recipe and build file into a bundle, and read back what it recorded."""
    (tmp_path / "bookshelf.yaml").write_text(recipe, encoding="utf-8")
    (tmp_path / "build.py").write_text(textwrap.dedent(build), encoding="utf-8")
    (tmp_path / "inputs").mkdir(exist_ok=True)
    (tmp_path / "inputs" / "raw.csv").write_text("region,value\nWorld,1\n", encoding="utf-8")
    run_record(
        build_path=None,
        recipe_path=tmp_path / "bookshelf.yaml",
        bundle_path=tmp_path / "bundle",
        version="v1.0.0",
        parameters=None,
        cwd=tmp_path,
    )
    return Bundle.read(tmp_path / "bundle")


def _named(bundle: Bundle, name: str) -> BundleResource:
    return next(resource for resource in bundle.manifest.resources if resource.name == name)


def test_the_recipe_accepts_the_discovery_fields_on_a_resource(tmp_path: Path) -> None:
    """The fields spell exactly as a book spells them, so a recipe reads in one vocabulary."""
    (tmp_path / "bookshelf.yaml").write_text(_RECIPE, encoding="utf-8")

    spec = load_record_recipe(tmp_path / "bookshelf.yaml").resolve("v1.0.0").resources["raw"]

    assert spec.description == "Somebody else's workbook."
    assert spec.authors is not None
    assert [author.name for author in spec.authors] == ["Upstream Modelling Team"]
    assert spec.authors[0].affiliation == "Not us"
    assert spec.license == "CC-BY-SA-4.0"
    assert spec.license_url == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert spec.doi == "10.5281/zenodo.1"
    assert spec.citation == "Upstream Modelling Team (2024)."
    assert spec.tags == ["upstream"]


def test_an_unknown_resource_key_still_names_the_keys_a_resource_takes(tmp_path: Path) -> None:
    """The rejection lists the widened key set, so an author sees where their field went."""
    recipe = _RECIPE.replace("        tags:\n          - upstream\n", "        author: nobody\n")
    (tmp_path / "bookshelf.yaml").write_text(recipe, encoding="utf-8")

    with pytest.raises(BookshelfError) as excinfo:
        load_record_recipe(tmp_path / "bookshelf.yaml")

    message = str(excinfo.value)
    assert "is not a recipe key" in message
    assert "authors" in message
    assert "license_url" in message


def test_a_declared_input_records_the_authors_the_recipe_gives_it(tmp_path: Path) -> None:
    raw = _named(_record(tmp_path), "raw")

    assert raw.authors == [models.Author(name="Upstream Modelling Team", affiliation="Not us")]
    assert raw.description == "Somebody else's workbook."
    assert raw.license == "CC-BY-SA-4.0"
    assert raw.license_url == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert raw.doi == "10.5281/zenodo.1"
    assert raw.citation == "Upstream Modelling Team (2024)."
    assert raw.tags == ["upstream"]


def test_a_written_output_records_the_authors_book_write_gives_it(tmp_path: Path) -> None:
    totals = _named(_record(tmp_path), "totals")

    assert totals.authors == [models.Author(name="Climate Resource")]
    assert totals.description == "What we made from it."
    assert totals.license == "CC-BY-4.0"
    assert totals.tags == ["derived"]


def test_the_input_and_the_output_keep_different_terms(tmp_path: Path) -> None:
    """The case the field exists for: one book, two licences, two author lists."""
    bundle = _record(tmp_path)

    assert _named(bundle, "raw").license == "CC-BY-SA-4.0"
    assert _named(bundle, "totals").license == "CC-BY-4.0"
    assert _named(bundle, "raw").authors != _named(bundle, "totals").authors


def test_a_resource_that_states_nothing_inherits_nothing_from_its_book(tmp_path: Path) -> None:
    """A book's authors are not a claim about any resource, so nothing is filled in."""
    recipe = _RECIPE[: _RECIPE.index("        description:")] + "\n"
    build = _BUILD.replace(
        '    description="What we made from it.",\n'
        '    authors=[{"name": "Climate Resource"}],\n'
        '    license="CC-BY-4.0",\n'
        '    tags=["derived"],\n',
        "",
    )
    bundle = _record(tmp_path, recipe=recipe, build=build)

    for name in ("raw", "totals"):
        resource = _named(bundle, name)
        assert resource.authors is None
        assert resource.description is None
        assert resource.license is None
        assert resource.tags == []
    assert bundle.manifest.book is not None
    assert bundle.manifest.book.authors == [{"name": "Climate Resource"}]


def test_a_book_overrides_only_the_resource_field_it_restates(tmp_path: Path) -> None:
    """A resource default is merged field by field, the way every other default is."""
    recipe = """\
volume:
  name: my-dataset
build:
  notebook: build.py
defaults:
  resources:
    raw:
      type: tabular
      license: CC-BY-SA-4.0
      authors:
        - name: Upstream Modelling Team
books:
  - version: "v1.0.0"
    license: CC-BY-4.0
    resources:
      raw:
        path: inputs/raw.csv
        authors:
          - name: A Different Upstream Team
"""
    (tmp_path / "bookshelf.yaml").write_text(recipe, encoding="utf-8")

    spec = load_record_recipe(tmp_path / "bookshelf.yaml").resolve("v1.0.0").resources["raw"]

    assert spec.license == "CC-BY-SA-4.0"
    assert spec.authors is not None
    assert [author.name for author in spec.authors] == ["A Different Upstream Team"]


def test_a_bookshelf_resource_states_no_catalogue_metadata_of_its_own(tmp_path: Path) -> None:
    """The platform already holds it, so declaring it is rejected rather than silently dropped."""
    recipe = """\
volume:
  name: my-dataset
build:
  notebook: build.py
books:
  - version: "v1.0.0"
    license: CC-BY-4.0
    resources:
      raw:
        uri: bookshelf://other/v1.0.0/data
        authors:
          - name: Upstream Modelling Team
        license: CC-BY-SA-4.0
"""
    (tmp_path / "bookshelf.yaml").write_text(recipe, encoding="utf-8")

    with pytest.raises(BookshelfError) as excinfo:
        load_record_recipe(tmp_path / "bookshelf.yaml")

    message = str(excinfo.value)
    assert "takes its catalogue metadata from the platform" in message
    assert "Remove authors, license" in message


def test_replay_sends_every_recorded_discovery_field(tmp_path: Path) -> None:
    """A recorded field that replay dropped would be attribution lost between the two."""
    bundle = _record(tmp_path)

    recorded: list[httpx.Request] = []
    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    sent = {resource["name"]: resource for resource in replayed(recorded)["resources"]}
    assert sent["raw"]["discovery"]["authors"] == [
        {"name": "Upstream Modelling Team", "affiliation": "Not us"}
    ]
    assert sent["raw"]["discovery"]["license"] == "CC-BY-SA-4.0"
    assert sent["raw"]["discovery"]["doi"] == "10.5281/zenodo.1"
    assert sent["totals"]["discovery"]["license"] == "CC-BY-4.0"
    assert sent["totals"]["discovery"]["description"] == "What we made from it."


def test_a_live_registration_puts_the_fields_on_the_wire(tmp_path: Path) -> None:
    """The recording path is not the only one, so the live sink states them too."""
    bundle = Bundle(tmp_path / "bundle")
    sink = RecordingSink(bundle, Mock(spec=BookshelfClient), ContentCache(tmp_path / "cache"))
    sink.draft_book("my-dataset", version="v1.0.0", license="CC-BY-4.0")

    resource = sink.register_external(
        type="tabular",
        uri="https://example.invalid/raw.csv",
        name="raw",
        authors=[models.Author(name="Upstream Modelling Team")],
        license="CC-BY-SA-4.0",
    )

    assert resource.metadata.discovery is not None
    assert resource.metadata.discovery.authors is not None
    assert resource.metadata.discovery.authors[0].name == "Upstream Modelling Team"
    assert _named(bundle, "raw").license == "CC-BY-SA-4.0"
