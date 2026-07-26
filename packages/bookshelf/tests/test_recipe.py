"""Tests for bookshelf.publisher.recipe — the bookshelf.yaml schema + parser."""

import textwrap
from pathlib import Path

import pytest

from bookshelf.publisher.recipe import (
    Recipe,
    load_recipe,
)


def _write_yaml(tmp_path: Path, content: str) -> Path:
    """Write ``content`` to ``tmp_path/bookshelf.yaml`` and return the path."""
    p = tmp_path / "bookshelf.yaml"
    p.write_text(textwrap.dedent(content))
    return p


VALID_SHA = "sha256:" + "a" * 64


def _valid_recipe_dict() -> dict:
    return {
        "collection": "ngfs-emissions",
        "license": "CC-BY-4.0",
        "authors": [{"name": "Mika Pflüger", "email": "mika@example.com"}],
        "books": [
            {
                "version": "v5.0",
                "license": "CC-BY-4.0",
                "visibility": "org",
                "inputs": {
                    "ngfs_phase5": {
                        "mode": "pointer",
                        "url": "doi:10.5281/zenodo.13989530",
                        "sha256": VALID_SHA,
                        "type": "timeseries",
                    }
                },
                "activity": {
                    "kind": "process",
                    "params": {"variable": "Emissions|*"},
                },
                "outputs": {
                    "emissions": {
                        "path": "outputs/emissions.parquet",
                        "type": "timeseries",
                        "name_in_book": "emissions",
                        "used": ["ngfs_phase5"],
                    }
                },
            }
        ],
    }


def test_valid_single_book_recipe():
    """A complete single-book recipe parses without errors."""
    recipe = Recipe.model_validate(_valid_recipe_dict())
    assert recipe.collection == "ngfs-emissions"
    assert len(recipe.books) == 1
    book = recipe.books[0]
    assert book.version == "v5.0"
    assert book.visibility == "org"
    assert "ngfs_phase5" in book.inputs
    assert book.inputs["ngfs_phase5"].mode == "pointer"
    assert "emissions" in book.outputs
    assert book.outputs["emissions"].used == ["ngfs_phase5"]


def test_valid_multi_book_recipe():
    """A recipe with multiple books parses all books."""
    data = _valid_recipe_dict()
    data["books"].append(
        {
            "version": "v6.0",
            "inputs": {
                "ngfs_phase6": {
                    "mode": "managed",
                    "url": "https://example.com/file.csv",
                    "sha256": VALID_SHA,
                    "type": "tabular",
                },
            },
            "outputs": {
                "out": {
                    "path": "outputs/out.parquet",
                    "type": "timeseries",
                    "name_in_book": "out",
                    "used": ["ngfs_phase6"],
                }
            },
        }
    )
    recipe = Recipe.model_validate(data)
    assert len(recipe.books) == 2
    assert recipe.books[1].version == "v6.0"


def test_default_visibility_is_hidden():
    """Omitting visibility defaults to 'hidden'."""
    data = _valid_recipe_dict()
    del data["books"][0]["visibility"]
    recipe = Recipe.model_validate(data)
    assert recipe.books[0].visibility == "hidden"


def test_default_activity_kind_is_process():
    """Omitting activity entirely defaults kind to 'process' with empty params."""
    data = _valid_recipe_dict()
    del data["books"][0]["activity"]
    recipe = Recipe.model_validate(data)
    assert recipe.books[0].activity.kind == "process"
    assert recipe.books[0].activity.params == {}


def test_default_input_mode_is_managed():
    """Omitting mode on an input defaults to 'managed'."""
    data = _valid_recipe_dict()
    del data["books"][0]["inputs"]["ngfs_phase5"]["mode"]
    recipe = Recipe.model_validate(data)
    assert recipe.books[0].inputs["ngfs_phase5"].mode == "managed"


def test_empty_used_list_is_valid():
    """An output with no used refs is valid (no lineage for simple outputs)."""
    data = _valid_recipe_dict()
    data["books"][0]["outputs"]["emissions"]["used"] = []
    recipe = Recipe.model_validate(data)
    assert recipe.books[0].outputs["emissions"].used == []


def test_optional_book_fields_absent():
    """license, description, and notebook can be omitted from a book."""
    data = _valid_recipe_dict()
    book = data["books"][0]
    book.pop("license", None)
    recipe = Recipe.model_validate(data)
    assert recipe.books[0].license is None
    assert recipe.books[0].description is None
    assert recipe.books[0].notebook is None


def test_notebook_path_parses():
    """notebook is accepted as a Path value."""
    data = _valid_recipe_dict()
    data["books"][0]["notebook"] = "notebooks/run.ipynb"
    recipe = Recipe.model_validate(data)
    assert recipe.books[0].notebook == Path("notebooks/run.ipynb")


def test_authors_optional():
    """Top-level authors is optional and defaults to an empty list."""
    data = _valid_recipe_dict()
    del data["authors"]
    recipe = Recipe.model_validate(data)
    assert recipe.authors == []


def test_unknown_top_level_key_rejected():
    """extra='forbid' on Recipe rejects unknown top-level keys."""
    data = _valid_recipe_dict()
    data["unexpected_field"] = "oops"
    with pytest.raises((ValueError, Exception), match="unexpected_field"):
        Recipe.model_validate(data)


def test_unknown_input_key_rejected():
    """extra='forbid' on InputSpec rejects unknown keys."""
    data = _valid_recipe_dict()
    data["books"][0]["inputs"]["ngfs_phase5"]["extra_key"] = "bad"
    with pytest.raises((ValueError, Exception)):
        Recipe.model_validate(data)


def test_unknown_output_key_rejected():
    """extra='forbid' on OutputSpec rejects unknown keys."""
    data = _valid_recipe_dict()
    data["books"][0]["outputs"]["emissions"]["extra_key"] = "bad"
    with pytest.raises((ValueError, Exception)):
        Recipe.model_validate(data)


def test_unknown_activity_key_rejected():
    """extra='forbid' on ActivitySpec rejects unknown keys."""
    data = _valid_recipe_dict()
    data["books"][0]["activity"]["unknown"] = "bad"
    with pytest.raises((ValueError, Exception)):
        Recipe.model_validate(data)


@pytest.mark.parametrize("bad_key", ["code_ref", "config_hash", "runner"])
def test_auto_derived_activity_key_rejected(bad_key: str):
    """Authoring code_ref, config_hash, or runner in the activity block is rejected."""
    data = _valid_recipe_dict()
    data["books"][0]["activity"][bad_key] = "some-value"
    with pytest.raises((ValueError, Exception), match=bad_key):
        Recipe.model_validate(data)


def test_used_ref_to_undeclared_input_rejected():
    """An output that references a non-existent input logical name is rejected."""
    data = _valid_recipe_dict()
    data["books"][0]["outputs"]["emissions"]["used"] = ["ngfs_phase5", "ghost_input"]
    with pytest.raises((ValueError, Exception), match="ghost_input"):
        Recipe.model_validate(data)


@pytest.mark.parametrize(
    "bad_sha",
    [
        "abc123",
        "sha256:tooshort",
        "sha256:" + "g" * 64,  # non-hex character
        "sha256:" + "a" * 63,  # one char too few
        "sha256:" + "a" * 65,  # one char too many
        "md5:abc",
    ],
)
def test_invalid_sha256_format_rejected(bad_sha: str):
    """InputSpec rejects any sha256 value that is not 'sha256:<64 hex digits>'."""
    data = _valid_recipe_dict()
    data["books"][0]["inputs"]["ngfs_phase5"]["sha256"] = bad_sha
    with pytest.raises((ValueError, Exception)):
        Recipe.model_validate(data)


def test_valid_sha256_format_accepted():
    """A correctly-formed sha256 value is accepted."""
    valid = "sha256:" + "0" * 64
    data = _valid_recipe_dict()
    data["books"][0]["inputs"]["ngfs_phase5"]["sha256"] = valid
    recipe = Recipe.model_validate(data)
    assert recipe.books[0].inputs["ngfs_phase5"].sha256 == valid


def test_empty_books_rejected():
    """A recipe with no books is invalid."""
    data = _valid_recipe_dict()
    data["books"] = []
    with pytest.raises((ValueError, Exception)):
        Recipe.model_validate(data)


def test_load_recipe_from_file(tmp_path: Path):
    """load_recipe reads and validates a YAML file on disk."""
    recipe_path = _write_yaml(
        tmp_path,
        f"""\
        collection: test-collection
        license: MIT
        books:
          - version: v1.0
            inputs:
              raw:
                url: https://example.com/data.csv
                sha256: {VALID_SHA}
                type: tabular
            outputs:
              result:
                path: outputs/result.parquet
                type: tabular
                name_in_book: result
                used: [raw]
        """,
    )
    recipe = load_recipe(recipe_path)
    assert recipe.collection == "test-collection"
    assert recipe.books[0].version == "v1.0"


def test_load_recipe_missing_file(tmp_path: Path):
    """load_recipe raises ValueError for a non-existent file."""
    missing = tmp_path / "no_such_file.yaml"
    with pytest.raises(ValueError, match="Cannot read recipe file"):
        load_recipe(missing)


def test_load_recipe_invalid_yaml(tmp_path: Path):
    """load_recipe raises ValueError for malformed YAML."""
    bad = tmp_path / "bookshelf.yaml"
    bad.write_text("key: [unclosed")
    with pytest.raises(ValueError, match="not valid YAML"):
        load_recipe(bad)


def test_load_recipe_not_a_mapping(tmp_path: Path):
    """load_recipe raises ValueError when the YAML root is not a mapping."""
    bad = tmp_path / "bookshelf.yaml"
    bad.write_text("- item1\n- item2\n")
    with pytest.raises(ValueError, match="YAML mapping"):
        load_recipe(bad)


def test_load_recipe_schema_error_is_valueerror(tmp_path: Path):
    """load_recipe wraps schema validation errors in ValueError."""
    recipe_path = _write_yaml(
        tmp_path,
        """\
        collection: test
        license: MIT
        books:
          - version: v1.0
            inputs:
              bad_input:
                url: https://example.com/data.csv
                sha256: not-valid-sha256
                type: tabular
        """,
    )
    with pytest.raises(ValueError, match="Invalid recipe"):
        load_recipe(recipe_path)
