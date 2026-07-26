"""Tests for bookshelf.publisher.lock — lock generation, serialization, masking."""

import uuid
from pathlib import Path
from uuid import UUID

import yaml

from bookshelf.publisher.lock import (
    AggregateLock,
    LockDocument,
    LockGenerated,
    build_aggregate_lock,
    build_lock,
    compute_config_hash,
    mask_aggregate_lock,
    mask_lock,
    recipe_book_canonical_bytes,
    serialize_aggregate_lock,
    serialize_lock,
    write_aggregate_lock,
)
from bookshelf.publisher.recipe import ActivitySpec, InputSpec, OutputSpec, RecipeBook

VALID_SHA = "sha256:" + "a" * 64
VALID_SHA_B = "sha256:" + "b" * 64
COLLECTION = "ngfs-emissions"
CODE_REF = "https://github.com/org/repo@abc1234"
CONFIG_HASH = "sha256:" + "c" * 64


def _make_recipe_book(
    *,
    version: str = "v5.0",
    inputs: dict | None = None,
    outputs: dict | None = None,
    activity: dict | None = None,
) -> RecipeBook:
    if inputs is None:
        inputs = {
            "raw": InputSpec(
                mode="pointer",
                url="doi:10.5281/zenodo.99",
                sha256=VALID_SHA,
                type="timeseries",
            )
        }
    if outputs is None:
        outputs = {
            "emissions": OutputSpec(
                path=Path("outputs/emissions.parquet"),
                type="timeseries",
                name_in_book="emissions",
                used=list(inputs.keys()),
            )
        }
    activity_spec = ActivitySpec(**(activity or {}))
    return RecipeBook(
        version=version,
        inputs=inputs,
        outputs=outputs,
        activity=activity_spec,
    )


def _make_lock_entry(
    *,
    recipe_book: RecipeBook | None = None,
    edition: int | None = 1,
    output_tracking_id: UUID | None = None,
) -> LockDocument:
    """Build a single per-book LockDocument entry."""
    book = recipe_book or _make_recipe_book()
    tid = output_tracking_id or uuid.uuid4()
    return build_lock(
        recipe_book=book,
        collection=COLLECTION,
        edition=edition,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"emissions": VALID_SHA_B},
        output_sizes={"emissions": 9123},
        output_tracking_ids={"emissions": tid},
    )


def test_build_lock_book_fields():
    """build_lock populates collection, version, and edition correctly."""
    entry = _make_lock_entry(edition=3)
    assert entry.book.collection == COLLECTION
    assert entry.book.version == "v5.0"
    assert entry.book.edition == 3


def test_build_lock_activity_fields():
    """build_lock populates activity with kind, code_ref, config_hash, params."""
    book = _make_recipe_book(activity={"kind": "process", "params": {"variable": "Emissions|*"}})
    entry = build_lock(
        recipe_book=book,
        collection=COLLECTION,
        edition=1,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"emissions": VALID_SHA_B},
        output_sizes={"emissions": 9123},
        output_tracking_ids={"emissions": uuid.uuid4()},
    )
    assert entry.activity.kind == "process"
    assert entry.activity.code_ref == CODE_REF
    assert entry.activity.config_hash == CONFIG_HASH
    assert entry.activity.params == {"variable": "Emissions|*"}


def test_build_lock_used_entries():
    """build_lock populates used[] from recipe inputs in declaration order."""
    entry = _make_lock_entry()
    assert len(entry.used) == 1
    used = entry.used[0]
    assert used.id == f"{COLLECTION}/raw"
    assert used.mode == "pointer"
    assert used.external_uri == "doi:10.5281/zenodo.99"
    assert used.sha256 == VALID_SHA


def test_build_lock_generated_entries():
    """build_lock populates generated[] from recipe outputs."""
    tid = uuid.uuid4()
    entry = _make_lock_entry(output_tracking_id=tid)
    assert len(entry.generated) == 1
    gen = entry.generated[0]
    assert gen.id == "emissions"
    assert gen.type == "timeseries"
    assert gen.name_in_book == "emissions"
    assert gen.sha256 == VALID_SHA_B
    assert gen.bytes == 9123
    assert gen.tracking_id == tid


def test_build_lock_with_notebook_items():
    """Notebook LockGenerated entries are appended after output entries."""
    nb_item = LockGenerated(
        id="notebook",
        type="document",
        name_in_book="notebook.ipynb",
        sha256=VALID_SHA,
        bytes=42,
        tracking_id=uuid.uuid4(),
    )
    entry = build_lock(
        recipe_book=_make_recipe_book(),
        collection=COLLECTION,
        edition=1,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"emissions": VALID_SHA_B},
        output_sizes={"emissions": 9123},
        output_tracking_ids={"emissions": uuid.uuid4()},
        notebook_items=[nb_item],
    )
    assert len(entry.generated) == 2
    assert entry.generated[1].id == "notebook"


def test_build_lock_edition_none():
    """edition=None is allowed (pre-publish draft state)."""
    entry = _make_lock_entry(edition=None)
    assert entry.book.edition is None


def test_build_lock_logical_key_namespacing():
    """used[].id is namespaced as '{collection}/{logical_name}'."""
    book = _make_recipe_book(
        inputs={
            "phase5": InputSpec(
                mode="managed", url="https://example.com/x.csv", sha256=VALID_SHA, type="tabular"
            )
        },
        outputs={
            "out": OutputSpec(
                path=Path("out.parquet"), type="tabular", name_in_book="out", used=["phase5"]
            )
        },
    )
    entry = build_lock(
        recipe_book=book,
        collection="my-collection",
        edition=1,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"out": VALID_SHA_B},
        output_sizes={"out": 100},
        output_tracking_ids={"out": uuid.uuid4()},
    )
    assert entry.used[0].id == "my-collection/phase5"


def test_lock_document_has_no_schema_version():
    """LockDocument (per-book entry) does not carry schema_version.

    schema_version belongs on AggregateLock, not on the per-book entry,
    so it doesn't appear spuriously inside each element of books[].
    """
    entry = _make_lock_entry()
    assert not hasattr(entry, "schema_version") or "schema_version" not in entry.model_fields


def test_build_aggregate_lock_single_book():
    """build_aggregate_lock wraps a single entry; schema_version is set."""
    entry = _make_lock_entry()
    agg = build_aggregate_lock([entry])
    assert agg.schema_version == "1.0"
    assert len(agg.books) == 1
    assert agg.books[0] is entry


def test_build_aggregate_lock_multi_book_preserves_order():
    """build_aggregate_lock keeps books in recipe declaration order."""
    book_a = _make_recipe_book(version="v1.0")
    book_b = _make_recipe_book(version="v2.0")
    entry_a = build_lock(
        recipe_book=book_a,
        collection=COLLECTION,
        edition=1,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"emissions": VALID_SHA_B},
        output_sizes={"emissions": 100},
        output_tracking_ids={"emissions": uuid.uuid4()},
    )
    entry_b = build_lock(
        recipe_book=book_b,
        collection=COLLECTION,
        edition=2,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"emissions": VALID_SHA_B},
        output_sizes={"emissions": 200},
        output_tracking_ids={"emissions": uuid.uuid4()},
    )
    agg = build_aggregate_lock([entry_a, entry_b])
    assert len(agg.books) == 2
    assert agg.books[0].book.version == "v1.0"
    assert agg.books[1].book.version == "v2.0"


def test_build_aggregate_lock_empty_is_valid():
    """build_aggregate_lock with an empty list produces a valid AggregateLock."""
    agg = build_aggregate_lock([])
    assert isinstance(agg, AggregateLock)
    assert agg.books == []


def test_mask_lock_removes_edition():
    """mask_lock sets book.edition to None."""
    entry = _make_lock_entry(edition=5)
    masked = mask_lock(entry)
    assert masked.book.edition is None
    # Original is not mutated.
    assert entry.book.edition == 5


def test_mask_lock_removes_tracking_ids():
    """mask_lock sets generated[].tracking_id to None for all items."""
    entry = _make_lock_entry()
    assert all(g.tracking_id is not None for g in entry.generated)
    masked = mask_lock(entry)
    assert all(g.tracking_id is None for g in masked.generated)
    # Original is not mutated.
    assert all(g.tracking_id is not None for g in entry.generated)


def test_mask_lock_preserves_other_fields():
    """mask_lock does not alter any other field."""
    entry = _make_lock_entry()
    masked = mask_lock(entry)
    assert masked.book.collection == entry.book.collection
    assert masked.book.version == entry.book.version
    assert masked.activity == entry.activity
    assert len(masked.used) == len(entry.used)
    g_orig = entry.generated[0]
    g_masked = masked.generated[0]
    assert g_masked.id == g_orig.id
    assert g_masked.sha256 == g_orig.sha256
    assert g_masked.bytes == g_orig.bytes


def test_mask_aggregate_lock_masks_all_entries():
    """mask_aggregate_lock strips edition and tracking_ids from every book."""
    entry_a = _make_lock_entry(edition=1)
    entry_b = _make_lock_entry(edition=2)
    agg = build_aggregate_lock([entry_a, entry_b])
    masked = mask_aggregate_lock(agg)
    assert masked.schema_version == agg.schema_version
    assert len(masked.books) == 2
    for book_entry in masked.books:
        assert book_entry.book.edition is None
        assert all(g.tracking_id is None for g in book_entry.generated)


def test_mask_aggregate_lock_does_not_mutate_original():
    """mask_aggregate_lock returns a new object; originals are unchanged."""
    entry = _make_lock_entry(edition=7)
    agg = build_aggregate_lock([entry])
    mask_aggregate_lock(agg)
    assert agg.books[0].book.edition == 7
    assert all(g.tracking_id is not None for g in agg.books[0].generated)


def test_serialize_lock_determinism():
    """Two serialize_lock calls on the same entry produce identical bytes."""
    entry = _make_lock_entry()
    assert serialize_lock(entry) == serialize_lock(entry)


def test_serialize_lock_determinism_after_rebuild():
    """Rebuilding the entry from the same inputs produces identical bytes."""
    book = _make_recipe_book()
    tid = uuid.uuid4()
    kwargs = {
        "recipe_book": book,
        "collection": COLLECTION,
        "edition": 1,
        "code_ref": CODE_REF,
        "config_hash": CONFIG_HASH,
        "output_hashes": {"emissions": VALID_SHA_B},
        "output_sizes": {"emissions": 9123},
        "output_tracking_ids": {"emissions": tid},
    }
    entry_a = build_lock(**kwargs)
    entry_b = build_lock(**kwargs)
    assert serialize_lock(entry_a) == serialize_lock(entry_b)


def test_serialize_lock_changes_when_hash_changes():
    """Changing an output hash produces different serialized bytes."""
    entry_a = _make_lock_entry()
    book = _make_recipe_book()
    entry_b = build_lock(
        recipe_book=book,
        collection=COLLECTION,
        edition=1,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"emissions": "sha256:" + "d" * 64},
        output_sizes={"emissions": 9123},
        output_tracking_ids={"emissions": uuid.uuid4()},
    )
    assert serialize_lock(entry_a) != serialize_lock(entry_b)


def test_serialize_lock_lf_line_endings():
    """serialize_lock always uses LF line endings."""
    entry = _make_lock_entry()
    raw = serialize_lock(entry)
    assert b"\r\n" not in raw
    assert b"\n" in raw


def test_serialize_lock_sorted_keys():
    """Top-level keys in the serialized YAML are in sorted order."""
    entry = _make_lock_entry()
    text = serialize_lock(entry).decode("utf-8")
    data = yaml.safe_load(text)
    keys_in_yaml = list(data.keys())
    assert keys_in_yaml == sorted(keys_in_yaml)


def test_masked_serialize_determinism():
    """Masked per-entry serialization is also deterministic (comparison contract)."""
    book = _make_recipe_book()
    tid = uuid.uuid4()
    kwargs = {
        "recipe_book": book,
        "collection": COLLECTION,
        "edition": 1,
        "code_ref": CODE_REF,
        "config_hash": CONFIG_HASH,
        "output_hashes": {"emissions": VALID_SHA_B},
        "output_sizes": {"emissions": 9123},
        "output_tracking_ids": {"emissions": tid},
    }
    bytes_a = serialize_lock(mask_lock(build_lock(**kwargs)))
    bytes_b = serialize_lock(mask_lock(build_lock(**kwargs)))
    assert bytes_a == bytes_b


def test_serialize_aggregate_lock_valid_yaml():
    """serialize_aggregate_lock output is valid YAML with schema_version."""
    entry = _make_lock_entry()
    agg = build_aggregate_lock([entry])
    data = yaml.safe_load(serialize_aggregate_lock(agg).decode("utf-8"))
    assert isinstance(data, dict)
    assert data["schema_version"] == "1.0"
    assert "books" in data
    assert isinstance(data["books"], list)
    assert len(data["books"]) == 1


def test_serialize_aggregate_lock_lf_line_endings():
    """serialize_aggregate_lock always uses LF line endings."""
    agg = build_aggregate_lock([_make_lock_entry()])
    raw = serialize_aggregate_lock(agg)
    assert b"\r\n" not in raw
    assert b"\n" in raw


def test_serialize_aggregate_lock_sorted_keys():
    """Top-level keys in the aggregate YAML are in sorted order."""
    agg = build_aggregate_lock([_make_lock_entry()])
    text = serialize_aggregate_lock(agg).decode("utf-8")
    data = yaml.safe_load(text)
    keys = list(data.keys())
    assert keys == sorted(keys)


def test_serialize_aggregate_lock_books_have_no_schema_version():
    """Each book entry in the YAML does not carry its own schema_version key."""
    entry = _make_lock_entry()
    agg = build_aggregate_lock([entry])
    data = yaml.safe_load(serialize_aggregate_lock(agg).decode("utf-8"))
    for book_data in data["books"]:
        assert "schema_version" not in book_data


def test_serialize_aggregate_lock_determinism():
    """serialize_aggregate_lock is byte-identical on repeated calls."""
    agg = build_aggregate_lock([_make_lock_entry()])
    assert serialize_aggregate_lock(agg) == serialize_aggregate_lock(agg)


def test_serialize_aggregate_lock_multi_book_preserves_order():
    """Books appear in recipe declaration order in the serialized YAML."""
    book_a = _make_recipe_book(version="v1.0")
    book_b = _make_recipe_book(version="v2.0")
    entry_a = build_lock(
        recipe_book=book_a,
        collection=COLLECTION,
        edition=1,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"emissions": VALID_SHA_B},
        output_sizes={"emissions": 100},
        output_tracking_ids={"emissions": uuid.uuid4()},
    )
    entry_b = build_lock(
        recipe_book=book_b,
        collection=COLLECTION,
        edition=2,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"emissions": VALID_SHA_B},
        output_sizes={"emissions": 200},
        output_tracking_ids={"emissions": uuid.uuid4()},
    )
    agg = build_aggregate_lock([entry_a, entry_b])
    data = yaml.safe_load(serialize_aggregate_lock(mask_aggregate_lock(agg)).decode("utf-8"))
    assert data["books"][0]["book"]["version"] == "v1.0"
    assert data["books"][1]["book"]["version"] == "v2.0"


def test_write_aggregate_lock_writes_masked_file(tmp_path: Path):
    """write_aggregate_lock writes the masked aggregate; edition and tracking_ids absent."""
    entry = _make_lock_entry(edition=3)
    agg = build_aggregate_lock([entry])
    lock_path = tmp_path / "bookshelf.lock"
    write_aggregate_lock(lock_path, agg)
    content = lock_path.read_text(encoding="utf-8")
    assert "edition" not in content
    assert "tracking_id" not in content
    # schema_version must be present at top level
    assert "schema_version" in content


def test_write_aggregate_lock_multi_book_single_file(tmp_path: Path):
    """Two books in one recipe produce one file with both entries."""
    book_a = _make_recipe_book(version="v1.0")
    book_b = _make_recipe_book(version="v2.0")
    entry_a = build_lock(
        recipe_book=book_a,
        collection=COLLECTION,
        edition=1,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"emissions": VALID_SHA_B},
        output_sizes={"emissions": 100},
        output_tracking_ids={"emissions": uuid.uuid4()},
    )
    entry_b = build_lock(
        recipe_book=book_b,
        collection=COLLECTION,
        edition=2,
        code_ref=CODE_REF,
        config_hash=CONFIG_HASH,
        output_hashes={"emissions": VALID_SHA_B},
        output_sizes={"emissions": 200},
        output_tracking_ids={"emissions": uuid.uuid4()},
    )
    lock_path = tmp_path / "bookshelf.lock"
    write_aggregate_lock(lock_path, build_aggregate_lock([entry_a, entry_b]))
    data = yaml.safe_load(lock_path.read_bytes())
    assert len(data["books"]) == 2
    versions = [b["book"]["version"] for b in data["books"]]
    assert versions == ["v1.0", "v2.0"]


def test_compute_config_hash_returns_sha256_prefix():
    """config hash always starts with 'sha256:'."""
    h = compute_config_hash(b"canonical-bytes")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_compute_config_hash_stable():
    """Same inputs always produce the same hash."""
    recipe_bytes = b"some canonical bytes"
    nb_bytes = b"notebook source"
    assert compute_config_hash(recipe_bytes, nb_bytes) == compute_config_hash(
        recipe_bytes, nb_bytes
    )


def test_compute_config_hash_differs_with_different_recipe():
    """Different recipe bytes -> different hash."""
    nb = b"notebook"
    h1 = compute_config_hash(b"recipe-v1", nb)
    h2 = compute_config_hash(b"recipe-v2", nb)
    assert h1 != h2


def test_compute_config_hash_differs_without_notebook():
    """Hash with and without notebook bytes differ."""
    recipe = b"recipe-bytes"
    h_with = compute_config_hash(recipe, b"notebook-content")
    h_without = compute_config_hash(recipe, None)
    assert h_with != h_without


def test_recipe_book_canonical_bytes_stable():
    """Same RecipeBook -> same canonical bytes."""
    book = _make_recipe_book()
    assert recipe_book_canonical_bytes(book) == recipe_book_canonical_bytes(book)


def test_recipe_book_canonical_bytes_differ_for_different_version():
    """RecipeBooks with different versions -> different canonical bytes."""
    book_a = _make_recipe_book(version="v5.0")
    book_b = _make_recipe_book(version="v6.0")
    assert recipe_book_canonical_bytes(book_a) != recipe_book_canonical_bytes(book_b)


def test_recipe_book_canonical_bytes_is_utf8():
    """Canonical bytes are valid UTF-8."""
    book = _make_recipe_book()
    bts = recipe_book_canonical_bytes(book)
    assert bts.decode("utf-8")  # no exception
