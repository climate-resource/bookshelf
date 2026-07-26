"""``bookshelf.lock`` is the generated, immutable lock artifact.

The lock is compiled from the realized publish state:
registered resources,
server-assigned tracking IDs,
and activity values.
It is committed to the producer repo alongside ``bookshelf.yaml``,
the way ``uv.lock`` or ``dvc.lock`` are.

Design
------
- **One file per recipe**:
  a recipe may declare several books.
  The written ``bookshelf.lock`` is a single :class:`AggregateLock`
  whose ``books[]`` holds one :class:`LockDocument`
  per book in recipe declaration order.
  Multi-book recipes therefore do not clobber one another.
- **Recipe/lock split**:
  the recipe declares *intent*.
  The lock records *realized provenance*:
  resolved hashes,
  minted tracking IDs,
  the server-assigned edition,
  and the full ``used``/``generated`` edge set.
- **Lineage by logical name**:
  ``used[]`` entries carry the logical name (``id``) from the recipe.
  Tracking IDs sent to the server as ``UsedRefByTrackingId``
  are already resolved client-side from the ingest result map.
  The backend's logical-key fallback stays rare.
- **Deterministic serialization**:
  ``serialize_lock`` produces byte-identical YAML
  when inputs remain unchanged.
  It uses sorted keys,
  explicit string formatting for hashes,
  no timestamps,
  LF newlines,
  and stable list order.

Committed-lock masking
-----------------------
The file **committed to the producer repo** omits server-assigned fields:

- ``book.edition`` (only known after ``publish``)
- ``generated[].tracking_id`` (server-assigned UUIDs)

This keeps the committed lock reviewable and diffable
without noise from server counters.
After a publish,
the full in-memory lock holds those fields for provenance.
``mask_lock`` strips them for the committed copy.

**Comparison contract**:
mask both sides,
then assert ``byte-identical`` via ``serialize_lock``.
Do not compare unmasked locks for equality across independent runs.

config_hash
-----------
``compute_config_hash`` hashes the canonical recipe-book bytes.
It can also hash the notebook source bytes.
The exact composition is **provisional**
and non-contractual until a working end-to-end flow exists.
Callers must not rely on a stable concatenation order across versions.
The result is recorded as ``Activity.config_hash`` provenance.
It is not consulted for idempotency.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field

from bookshelf._core.hashing import canonical_json_bytes, sha256_hex
from bookshelf.publisher.recipe import RecipeBook

LOCK_SCHEMA_VERSION = "1.0"


class LockBook(BaseModel):
    """Identity section of the lock: collection, version, and server-assigned edition."""

    model_config = ConfigDict(extra="forbid")

    collection: str
    version: str
    edition: int | None = None  # None in the committed file (server-assigned, masked out)


class LockActivity(BaseModel):
    """Realized activity provenance recorded in the lock."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    code_ref: str
    config_hash: str
    params: dict[str, Any] = Field(default_factory=dict)


class LockUsed(BaseModel):
    """One raw input in the lock's ``used[]`` list.

    ``id`` is the logical name from the recipe,
    namespaced as ``{collection}/{name}``.
    ``external_uri`` / ``url`` is the original source URL or DOI.
    """

    model_config = ConfigDict(extra="forbid")

    id: str  # logical name (logical_key)
    mode: str  # "managed" | "pointer"
    external_uri: str  # original url / doi
    sha256: str


class LockGenerated(BaseModel):
    """One output or notebook resource in the lock's ``generated[]`` list.

    ``tracking_id`` is ``None`` in the committed file.
    It is server-assigned
    and masked out by ``mask_lock``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str  # logical name
    type: str
    name_in_book: str
    sha256: str
    bytes: int
    tracking_id: UUID | None = None  # masked out in committed file


class LockDocument(BaseModel):
    """One book's realized provenance: a single entry of the aggregate lock.

    A recipe may declare several books.
    Each book compiles to one of these entries.
    The entries are gathered under :class:`AggregateLock`,
    which is the artifact written to ``bookshelf.lock``.
    The enclosing :class:`AggregateLock` carries ``schema_version``.
    Per-book entries therefore nest cleanly under ``AggregateLock.books``.
    """

    model_config = ConfigDict(extra="forbid")

    book: LockBook
    activity: LockActivity
    used: list[LockUsed] = Field(default_factory=list)
    generated: list[LockGenerated] = Field(default_factory=list)


class AggregateLock(BaseModel):
    """The full ``bookshelf.lock`` document for one recipe.

    A recipe declares one or more books.
    This aggregate holds one :class:`LockDocument` per book
    under ``books`` in **recipe declaration order**.
    The aggregate is the artifact written to ``bookshelf.lock``.
    It is one file per recipe,
    so multi-book recipes no longer clobber one another.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = LOCK_SCHEMA_VERSION
    books: list[LockDocument] = Field(default_factory=list)


def build_lock(
    *,
    recipe_book: RecipeBook,
    collection: str,
    edition: int | None,
    code_ref: str,
    config_hash: str,
    output_hashes: dict[str, str],
    output_sizes: dict[str, int],
    output_tracking_ids: dict[str, UUID],
    notebook_items: list[LockGenerated] | None = None,
) -> LockDocument:
    """Assemble a :class:`LockDocument` from the realized publish state.

    Parameters
    ----------
    recipe_book:
        The :class:`~bookshelf.publisher.recipe.RecipeBook` being published.
    collection:
        The Volume or collection slug.
        It namespaces logical keys
        and populates ``book.collection``.
    edition:
        Server-assigned edition integer, or ``None`` before the publish step.
    code_ref:
        ``{remote_url}@{sha}`` derived from the producer's git repo.
    config_hash:
        ``sha256:…`` hash of the recipe book section + notebook source bytes.
    output_hashes:
        Mapping from logical output name → ``sha256:<hex>`` of the local file.
    output_sizes:
        Mapping from logical output name → byte count of the local file.
    output_tracking_ids:
        Mapping from logical output name
        to the tracking ID returned by the server
        after registering the output resource.
    notebook_items:
        Optional :class:`LockGenerated` entries
        for executed notebook resources of type ``DOCUMENT``.
        The notebook-capture worker adds them.

    Returns
    -------
    LockDocument
        The fully populated lock document.
    """
    # --- used[]: one entry per recipe input ---
    used: list[LockUsed] = []
    for name, spec in recipe_book.inputs.items():
        logical_key = f"{collection}/{name}"
        used.append(
            LockUsed(
                id=logical_key,
                mode=spec.mode,
                external_uri=spec.url,
                sha256=spec.sha256,
            )
        )

    # --- generated[]: one entry per recipe output (+ notebooks) ---
    generated: list[LockGenerated] = []
    for out_name, out_spec in recipe_book.outputs.items():
        generated.append(
            LockGenerated(
                id=out_name,
                type=out_spec.type,
                name_in_book=out_spec.name_in_book,
                sha256=output_hashes[out_name],
                bytes=output_sizes[out_name],
                tracking_id=output_tracking_ids.get(out_name),
            )
        )
    if notebook_items:
        generated.extend(notebook_items)

    return LockDocument(
        book=LockBook(
            collection=collection,
            version=recipe_book.version,
            edition=edition,
        ),
        activity=LockActivity(
            kind=recipe_book.activity.kind,
            code_ref=code_ref,
            config_hash=config_hash,
            params=dict(recipe_book.activity.params),
        ),
        used=used,
        generated=generated,
    )


def build_aggregate_lock(entries: list[LockDocument]) -> AggregateLock:
    """Assemble the top-level :class:`AggregateLock` from per-book entries.

    Parameters
    ----------
    entries:
        Per-book :class:`LockDocument` objects in **recipe declaration order**.
        The publish loop typically calls :func:`build_lock` once per book.
        It passes the accumulated list here after the loop.

    Returns
    -------
    AggregateLock
        The complete aggregate lock ready for serialization and writing.
    """
    return AggregateLock(books=list(entries))


def mask_lock(lock: LockDocument) -> LockDocument:
    """Return a copy of ``lock`` with server-assigned fields removed.

    Drops:
    - ``book.edition`` (server-assigned integer. Set to ``None``)
    - ``generated[].tracking_id`` (server-assigned UUID. Set to ``None``)

    The masked copy is committed to the producer repo.
    To compare two independent publish runs,
    mask both sides
    and call ``serialize_lock`` on each.
    The bytes must be identical when the inputs are identical.
    """
    masked_generated = [item.model_copy(update={"tracking_id": None}) for item in lock.generated]
    masked_book = lock.book.model_copy(update={"edition": None})
    return lock.model_copy(update={"book": masked_book, "generated": masked_generated})


def _sort_recursive(obj: Any) -> Any:  # noqa: ANN401
    """Recursively sort every mapping by key, preserving list order.

    Both lock serialization and ``config_hash`` computation
    use this canonicalization.
    They therefore cannot drift apart.
    """
    if isinstance(obj, dict):
        return {k: _sort_recursive(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_sort_recursive(item) for item in obj]
    return obj


def _model_to_sorted_dict(model: BaseModel) -> dict[str, Any]:
    """Convert a pydantic model to a plain dict for YAML serialisation.

    Omits ``None`` values,
    including masked fields and optional defaults.
    Recursively sorts every mapping by key for determinism.
    Preserves list order,
    so ``books[]`` keeps recipe declaration order.
    """
    result: dict[str, Any] = _sort_recursive(model.model_dump(mode="json", exclude_none=True))
    return result


def _dump_sorted_yaml(model: BaseModel) -> bytes:
    """Serialize any lock model to deterministic YAML bytes (LF, UTF-8).

    Output is byte-identical across runs with unchanged inputs.
    It uses sorted keys,
    no timestamps,
    no line wrapping,
    and stable list order.
    """
    text = yaml.dump(
        _model_to_sorted_dict(model),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
        width=10000,  # do not line-wrap long strings
    )
    # yaml.dump uses LF on all platforms in PyYAML >= 6, but be explicit.
    text_str: str = str(text)
    normalized = text_str.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.encode("utf-8")


def serialize_lock(lock: LockDocument) -> bytes:
    """Serialize a per-book lock entry to deterministic YAML bytes."""
    return _dump_sorted_yaml(lock)


def mask_aggregate_lock(lock: AggregateLock) -> AggregateLock:
    """Return a copy of ``lock`` with each book's server-assigned fields removed.

    Applies :func:`mask_lock` to every entry in ``books``.
    This drops ``book.edition``
    and each ``generated[].tracking_id``.
    Entry order is preserved.
    """
    return lock.model_copy(update={"books": [mask_lock(book) for book in lock.books]})


def serialize_aggregate_lock(lock: AggregateLock) -> bytes:
    """Serialize an aggregate lock to deterministic YAML bytes (LF, UTF-8).

    Output is byte-identical across runs with unchanged inputs.
    It uses sorted keys,
    no timestamps,
    and stable book order.
    Recipe declaration order is preserved as list order.
    Mapping keys within each book are sorted.
    """
    return _dump_sorted_yaml(lock)


def write_aggregate_lock(path: Path, lock: AggregateLock) -> None:
    """Write the masked committed aggregate lock to ``path``.

    Always applies ``mask_aggregate_lock`` first.
    The committed file therefore never contains server-assigned fields.
    """
    path.write_bytes(serialize_aggregate_lock(mask_aggregate_lock(lock)))


def compute_config_hash(
    recipe_book_canonical_bytes: bytes,
    notebook_source_bytes: bytes | None = None,
) -> str:
    """Compute a provisional ``sha256:<hex>`` config hash.

    The hash covers the canonical recipe-book bytes,
    which are deterministic YAML of the recipe book section.
    It can also cover the notebook source bytes.

    **Non-contractual**:
    the exact concatenation is provisional
    and may change before a stable release.
    The hash is recorded as ``Activity.config_hash`` for provenance only.
    The platform never consults it to decide whether to publish.
    """
    return sha256_hex(recipe_book_canonical_bytes + (notebook_source_bytes or b""))


def recipe_book_canonical_bytes(recipe_book: RecipeBook) -> bytes:
    """Return deterministic bytes representing a recipe book section.

    Used as the first input to :func:`compute_config_hash`.
    The serialisation is ``json``-mode pydantic dump with sorted keys.
    """
    raw = _sort_recursive(recipe_book.model_dump(mode="json", exclude_none=True))
    return canonical_json_bytes(raw)


__all__ = [
    "AggregateLock",
    "LockActivity",
    "LockBook",
    "LockDocument",
    "LockGenerated",
    "LockUsed",
    "LOCK_SCHEMA_VERSION",
    "build_aggregate_lock",
    "build_lock",
    "compute_config_hash",
    "mask_aggregate_lock",
    "mask_lock",
    "recipe_book_canonical_bytes",
    "serialize_aggregate_lock",
    "serialize_lock",
    "write_aggregate_lock",
]
