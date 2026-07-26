"""The record/replay bundle is an on-disk, replayable lock using manifest schema v1.

A bundle extends the ADR-0007 lock so it is self-contained and replayable.
It holds a manifest and the content-addressed bytes of every referenced resource.
A recorded publish can therefore be reviewed offline and replayed byte-for-byte.

Layout
------
::

    bundle/
      manifest.lock          # realised PROV state: the ADR-0007 lock, extended
      resources/
        <sha256>.parquet     # content-addressed serialised resource bytes

The byte file name contains only the hex digest,
with the ``sha256:`` prefix removed and an extension added from the resource type.
The directory is content addressed,
so identical bytes share one file.

Manifest schema
---------------
The manifest is intentionally **minimal**: only what record/replay needs:

- A header carrying ``schema_version`` (``BUNDLE_SCHEMA_VERSION``).
- ``resources`` contains one :class:`BundleResource` per registration.
  Each record has ``tracking_id``, ``hash``, ``type``, and ``logical_key``.
  Each record carries an explicit ``kind`` discriminator:

  - ``"managed"`` means the platform re-hosts the bytes.
    The record carries ``size`` and stores bytes at ``resources/<hex>.<ext>``.
    For an activity output,
    ``generated`` marks the output and ``used`` records its input references.
  - ``"pointer"`` means the platform must not re-host the external resource.
    The record carries ``external_uri`` and no byte file or ``size``.
    A hashless pointer receives the same synthetic hash that the backend computes.

  The discriminator is **explicit**, never inferred from a missing field.

- ``activity``: the optional :class:`BundleActivity` envelope (``activity_id``,
  ``kind``, ``code_ref``, ``config_hash``, ``parameters``, ``runner``) captured
  on the first activity-wrapped register.

The activity envelope is optional.
A managed-only bundle with no activity still loads and replays unchanged.
The ``used`` references are recorded by ``tracking_id`` or ``logical_key``.
Replay does not resolve them again,
so the edition's lineage is exactly what the notebook expressed.

- ``book`` contains the optional :class:`BundleBook` framing.
  Replay keys the draft on the content bundle hash,
  attaches each entry,
  and publishes.
  Two replays of the same bundle therefore converge on one published edition.

The bundle is pre-edition.
The server assigns the edition during replay,
and the book framing never carries one.
Within the supported major,
the reader tolerates unknown fields from a newer minor version.
A newer major version is refused rather than reinterpreted.

Serialisation reuses :func:`~bookshelf.publisher.lock._dump_sorted_yaml`.
The manifest therefore has the same on-disk shape as ``bookshelf.lock``.
It uses sorted keys,
LF newlines,
and no timestamps.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bookshelf._core.hashing import canonical_json_bytes
from bookshelf.publisher.lock import _dump_sorted_yaml

BUNDLE_SCHEMA_VERSION = "1.0"

# The major this reader models. A newer *minor* is additive and loads (the models
# ignore unknown fields), but a newer *major* signals a breaking change, so
# reading it under v1 semantics would drop fields that carry new meaning.
_SUPPORTED_SCHEMA_MAJOR = int(BUNDLE_SCHEMA_VERSION.split(".", 1)[0])

MANIFEST_NAME = "manifest.lock"
RESOURCES_DIRNAME = "resources"

# Map a resource ``type`` to the byte-file extension under ``resources/``.
# Mirrors ``serialise.py``: parquet for the frame types, opaque otherwise.
_PARQUET_TYPES = frozenset({"timeseries", "tabular"})

# A canonical resource hash is ``sha256:`` + exactly 64 lowercase hex chars.
# Validating against this before deriving a byte-file name keeps the path
# component a clean digest with no ``:``, ``/``, or ``.`` characters.
# A crafted manifest hash therefore cannot traverse out of ``resources/``.
_SHA256_RE = re.compile(r"^sha256:([0-9a-f]{64})$")


def _sha256_hex(hash_: str) -> str:
    """Return the 64-char hex digest of a canonical ``sha256:<hex>`` hash.

    Raises :class:`ValueError` for anything that is not exactly
    ``sha256:`` + 64 lowercase hex chars, so the result is always safe to use
    as a filesystem path component.
    """
    match = _SHA256_RE.match(hash_)
    if match is None:
        raise ValueError("hash must be canonical 'sha256:<64-lowercase-hex>'")
    return match.group(1)


class BundleUsedRef(BaseModel):
    """One recorded ``used`` input reference (exactly one of two coordinates).

    Mirrors the wire ``UsedRef`` union.
    A ``used`` input is referenced **either** by ``tracking_id``
    **or** by ``logical_key``.
    The reference is recorded verbatim and replayed as-is.
    It is *not* re-resolved at replay,
    so the lineage edges the backend mints are exactly what was recorded.

    ``extra="ignore"`` keeps the record tolerant.
    ``exclude_none`` on dump keeps the unused coordinate off the wire,
    so the replayed envelope stays the unambiguous one-of shape
    that the server validates.
    """

    model_config = ConfigDict(extra="ignore")

    tracking_id: UUID | None = None
    logical_key: str | None = None

    @model_validator(mode="after")
    def _exactly_one_coordinate(self) -> BundleUsedRef:
        if (self.tracking_id is None) == (self.logical_key is None):
            raise ValueError("BundleUsedRef requires exactly one of tracking_id or logical_key")
        return self


# The shelf slug the backend funnels an ``external_uri`` through before it
# synthesises a hash (``LocationInput(shelf="external", path=external_uri)``).
_EXTERNAL_SHELF = "external"


def synthesise_pointer_hash(
    *,
    type_: str,
    external_uri: str,
    logical_key: str | None = None,
) -> str:
    """Synthesise the canonical hash of a hashless external pointer.

    Mirrors the backend's ``_synthesise_hash`` exactly.
    The digest is computed over
    ``{type, sorted(locations), logical_key or ''}``.
    The external URI is funnelled through the ``external`` shelf,
    so the bundle records the hash that the backend would assign
    to a hashless pointer.
    Replay always sends this recorded hash,
    so the two never diverge.
    """
    locations = [(_EXTERNAL_SHELF, external_uri)]
    seed = json.dumps(
        {
            "type": type_,
            "logical_key": logical_key or "",
            "locations": locations,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(seed).hexdigest()}"


class BundleResource(BaseModel):
    """One resource recorded in the bundle manifest.

    Pre-edition: ``hash`` is the canonical ``sha256:<hex>`` and drives the
    replay registration's idempotency.  ``kind`` is the **explicit** discriminator
    between the two variants:

    - ``"managed"``: the platform re-hosts the bytes, ``hash`` is the digest of
      the bytes stored at ``resources/<hex>.<ext>`` and ``size`` is their length.
      When produced inside an activity, ``generated`` marks it as an activity
      output and ``used`` carries the input references for its lineage edges.
    - ``"pointer"``: an external pointer (``register_external``), ``external_uri``
      is the target the platform must not re-host, there is no byte file, and
      ``size`` is omitted.

    ``extra="ignore"`` keeps the *per-resource* record forward-compatible too:
    the book-framing slice adds fields like ``name_in_book`` per entry, and an
    older reader must still load them by dropping what it does not model.
    """

    model_config = ConfigDict(extra="ignore")

    tracking_id: UUID
    hash: str  # canonical ``sha256:<hex>``
    type: str
    kind: Literal["managed", "pointer"] = "managed"
    logical_key: str | None = None
    format: str | None = None  # declared storage format, ``None`` when unknown
    visibility: Literal["hidden", "org", "public"] = "hidden"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    dedupe: bool = True
    size: int | None = None  # byte length of a managed resource, ``None`` for a pointer
    external_uri: str | None = None  # the pointer target, ``None`` for a managed resource
    generated: bool = False
    used: list[BundleUsedRef] = Field(default_factory=list)


class BundleActivity(BaseModel):
    """The activity envelope recorded in the bundle manifest.

    Mirrors the wire :class:`~bookshelf.publisher._models.ActivityCreate` (minus its
    build-level ``used``, which is recorded per resource): the client-minted
    ``activity_id`` plus the descriptive fields.  Replay creates the activity
    under this exact ``activity_id``, so re-replay finds it already present and
    mints no duplicate provenance edges (idempotent on ``activity_id``).

    ``extra="ignore"`` keeps the envelope tolerant of fields a later client adds.
    """

    model_config = ConfigDict(extra="ignore")

    activity_id: UUID
    kind: str
    code_ref: str
    config_hash: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    runner: str | None = None


class BundleBookEntry(BaseModel):
    """One ``name_in_book -> resource`` membership row in the book framing.

    ``tracking_id`` references a resource recorded in the same manifest (managed
    or pointer), ``name_in_book`` is the stable name the resource takes inside the
    book.  The pair feeds the bundle-hash seal (sorted ``[name_in_book,
    sha256_hex]`` members), so it is the unit replay attaches and the unit the
    idempotency key is computed over.

    ``extra="ignore"`` keeps the row tolerant of fields a later client adds.
    """

    model_config = ConfigDict(extra="ignore")

    name_in_book: str
    tracking_id: UUID


class BundleBook(BaseModel):
    """The book framing recorded in the bundle manifest (pre-edition).

    Mirrors the ``create_draft_book -> attach_entry* -> publish`` arc the producer
    expressed: ``volume`` / ``version`` / ``visibility`` / ``license`` frame the
    draft, ``entries`` carry the ``name_in_book -> resource`` membership, and
    ``published`` records whether replay should publish the draft (vs. leave it a
    draft).  ``authors`` is recorded for provenance only: the draft API carries
    no authors field and the seal excludes them, so replay never sends them.

    It is **pre-edition** (no ``edition`` field): the server assigns the edition
    at replay (ADR 0006), and replay keys the draft on the content bundle hash
    computed from this framing, so two replays of the same bundle converge on one
    edition.  ``extra="ignore"`` keeps it tolerant of fields a later client adds.
    """

    model_config = ConfigDict(extra="ignore")

    volume: str
    version: str
    visibility: str = "hidden"
    license: str | None = None
    authors: list[dict[str, Any]] = Field(default_factory=list)
    description: str | None = None
    citation_doi: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    entries: list[BundleBookEntry] = Field(default_factory=list)
    published: bool = False


class BundleManifest(BaseModel):
    """The bundle's ``manifest.lock`` document.

    Carries the schema version, the optional ``activity`` envelope, the optional
    ``book`` framing, and the managed ``resources``.  ``model_config`` uses
    ``extra="ignore"`` so a manifest written by a later *minor* still loads here,
    silently dropping fields this version does not model (the
    forward-compatibility contract for the tracer).  A newer *major* is refused
    by :meth:`Bundle.read` before validation rather than reinterpreted here.

    ``activity`` is ``None`` for a managed-only bundle and ``book`` is ``None``
    for a resources-only bundle, so each extension is additive: a bundle without
    them loads and replays exactly as it did before the extension landed.
    """

    # Tolerant of added fields: later slices extend the manifest, and an older
    # reader must still load a newer bundle.
    model_config = ConfigDict(extra="ignore")

    schema_version: str = BUNDLE_SCHEMA_VERSION
    activity: BundleActivity | None = None
    book: BundleBook | None = None
    resources: list[BundleResource] = Field(default_factory=list)
    # TODO(#210 follow-up): capture the pyarrow version in the manifest header so
    # replay can flag a writer-version mismatch that would break byte parity.


def _check_schema_major(raw: dict[str, Any]) -> None:
    """Refuse a manifest whose major schema version this reader cannot model.

    A newer minor is forward-compatible: the models ignore unknown fields, so an
    additive change still loads. A newer major signals a breaking change, so
    loading it under the current semantics could silently drop fields that carry
    new meaning. Raise rather than misinterpret the bundle.
    """
    version = raw.get("schema_version", BUNDLE_SCHEMA_VERSION)
    if not isinstance(version, str):
        raise ValueError(f"bundle schema_version must be a string, got {version!r}")
    try:
        major = int(version.split(".", 1)[0])
    except ValueError as exc:
        raise ValueError(f"bundle schema_version {version!r} is not a valid version") from exc
    if major > _SUPPORTED_SCHEMA_MAJOR:
        raise ValueError(
            f"bundle schema_version {version!r} is a newer major than this client models "
            f"(schema {BUNDLE_SCHEMA_VERSION}). Upgrade bookshelf to read it."
        )


def resource_filename(hash_: str, type_: str) -> str:
    """Return the content-addressed byte-file name for ``hash_`` of ``type_``.

    Validates ``hash_`` is a canonical ``sha256:<hex>`` (raising
    :class:`ValueError` otherwise), then uses the bare 64-hex digest plus a
    type-derived extension: so ``resources/`` is keyed purely on content and a
    crafted hash cannot escape the directory.
    """
    hex_digest = _sha256_hex(hash_)
    extension = "parquet" if type_ in _PARQUET_TYPES else "bin"
    return f"{hex_digest}.{extension}"


def compute_book_bundle_hash(manifest: BundleManifest) -> str:
    """Return the content bundle hash for the manifest's book framing.

    This is the client-side mirror of the backend ``_compute_bundle_hash`` seal
    and **must** stay byte-identical to it: it is the draft idempotency key, so
    any drift makes replay mint a fresh edition (or fail the publish
    recompute-assert).  The canonicalisation is, over one canonical JSON document
    (sorted keys, ``(",", ":")`` separators) via the shared
    :func:`~bookshelf._core.hashing.canonical_json_bytes`:

    - ``license``: the book's SPDX license (``None`` when unset), and
    - ``members``: the **sorted** list of ``[name_in_book, sha256_hex]`` pairs,
      where ``sha256_hex`` is the validated 64-char lowercase hex of each member
      resource's canonical ``sha256:<hex>`` hash, and
    - ``visibility``: the book's three-tier visibility value.

    Each entry's resource is resolved from the manifest by ``tracking_id``.  The
    digest is the 64-char lowercase hex (no ``sha256:`` prefix), matching the
    backend's ``hexdigest()`` and the ``bundle_hash`` wire field.

    Raises :class:`ValueError` if the manifest has no book framing, an entry
    references a resource not recorded here, or a member resource carries no
    canonical sha256 hash (the seal would be ambiguous).
    """
    if manifest.book is None:
        raise ValueError("manifest has no book framing to hash")
    resource_by_id = {resource.tracking_id: resource for resource in manifest.resources}
    members: list[list[str]] = []
    for entry in manifest.book.entries:
        resource = resource_by_id.get(entry.tracking_id)
        if resource is None:
            raise ValueError(
                f"book entry {entry.name_in_book!r} references resource "
                f"{entry.tracking_id} that is not recorded in this bundle"
            )
        try:
            hex_digest = _sha256_hex(resource.hash)
        except ValueError as exc:
            raise ValueError(
                f"book entry {entry.name_in_book!r} resource has no canonical sha256 "
                "hash, so cannot compute bundle hash"
            ) from exc
        members.append([entry.name_in_book, hex_digest])
    members.sort()
    payload = {
        "license": manifest.book.license,
        "members": members,
        "visibility": manifest.book.visibility,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class Bundle:
    """A bundle directory on disk: the manifest plus ``resources/`` bytes.

    Construct one over a (possibly empty) directory, :meth:`add_resource` writes
    a content-addressed byte file and appends a manifest record, :meth:`write`
    flushes the manifest, and :meth:`read` loads an existing bundle.
    """

    def __init__(self, root: Path, manifest: BundleManifest | None = None) -> None:
        self.root = root
        self.manifest = manifest if manifest is not None else BundleManifest()

    @property
    def resources_dir(self) -> Path:
        """The ``resources/`` subdirectory holding content-addressed bytes."""
        return self.root / RESOURCES_DIRNAME

    @property
    def manifest_path(self) -> Path:
        """The path to ``manifest.lock`` within the bundle."""
        return self.root / MANIFEST_NAME

    def set_activity(self, activity: BundleActivity) -> None:
        """Record the activity envelope on the manifest (first call wins).

        Recording a second envelope that differs in any field is a programming
        error because a bundle is one build, so a mismatch raises :class:`ValueError`.
        re-recording the *identical* envelope is a no-op.
        """
        if self.manifest.activity is not None:
            if self.manifest.activity != activity:
                raise ValueError("bundle already has a different activity recorded")
            return
        self.manifest.activity = activity

    def set_book(self, book: BundleBook) -> None:
        """Record the book framing on the manifest (one book per bundle).

        A bundle records a single book's draft/attach/publish arc, so a second
        ``set_book`` raises :class:`ValueError`.  Entries are appended later with
        :meth:`add_book_entry`, and :meth:`mark_book_published` flips the publish
        flag: both mutate the framing recorded here.
        """
        if self.manifest.book is not None:
            raise ValueError("bundle already has a book recorded")
        self.manifest.book = book

    def add_book_entry(self, *, name_in_book: str, tracking_id: UUID) -> BundleBookEntry:
        """Append a ``name_in_book -> resource`` entry to the recorded book.

        ``tracking_id`` must reference a resource already recorded in this
        manifest, so the bundle stays self-contained and the bundle hash can
        always be computed from the membership.  ``name_in_book`` must be unique
        within the book (the backend enforces the same), so a duplicate raises
        :class:`ValueError` here rather than failing at replay.  Raises
        :class:`ValueError` if no book has been drafted yet.
        """
        if self.manifest.book is None:
            raise ValueError("cannot attach a book entry before the book is drafted")
        if any(entry.name_in_book == name_in_book for entry in self.manifest.book.entries):
            raise ValueError(f"book entry name {name_in_book!r} already used in this book")
        if all(resource.tracking_id != tracking_id for resource in self.manifest.resources):
            raise ValueError(
                f"book entry {name_in_book!r} references resource {tracking_id} "
                "that is not recorded in this bundle"
            )
        entry = BundleBookEntry(name_in_book=name_in_book, tracking_id=tracking_id)
        self.manifest.book.entries.append(entry)
        return entry

    def mark_book_published(self) -> None:
        """Mark the recorded book to be **published** on replay.

        Without this, replay drafts and attaches but leaves the book a draft.
        Raises :class:`ValueError` if no book has been drafted yet.
        """
        if self.manifest.book is None:
            raise ValueError("cannot publish before the book is drafted")
        self.manifest.book.published = True

    def add_resource(
        self,
        *,
        data: bytes,
        hash_: str,
        type_: str,
        tracking_id: UUID,
        logical_key: str | None = None,
        format_: str | None = None,
        visibility: str = "hidden",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        dedupe: bool = True,
        generated: bool = False,
        used: list[BundleUsedRef] | None = None,
    ) -> BundleResource:
        """Write ``data`` to ``resources/<hex>`` and append a manifest record.

        The byte file is named from ``hash_`` (content-addressed), so recording
        the same bytes twice is a no-op write.  Returns the appended
        :class:`BundleResource`.

        ``generated`` and ``used`` carry the resource's lineage when it was
        produced inside an activity: ``generated`` marks it as an activity
        output, and ``used`` records the input references verbatim.  Both default
        to the no-lineage case, so a plain managed registration records as
        before.

        ``hash_`` must be the canonical ``sha256:<hex>`` of ``data``: the digest
        is recomputed and verified before any write (raising :class:`ValueError`
        on a mismatch), so the content-addressed name always matches the bytes.
        In the happy path this already holds: the hash comes from the shared
        serialiser: but the check is defence-in-depth against a forged hash.
        """
        expected = "sha256:" + hashlib.sha256(data).hexdigest()
        if hash_ != expected:
            raise ValueError(f"hash {hash_!r} does not match bytes (expected {expected!r})")
        self.resources_dir.mkdir(parents=True, exist_ok=True)
        byte_path = self.resources_dir / resource_filename(hash_, type_)
        byte_path.write_bytes(data)
        record = BundleResource(
            tracking_id=tracking_id,
            hash=hash_,
            type=type_,
            kind="managed",
            logical_key=logical_key,
            format=format_,
            visibility=visibility,
            tags=list(tags or []),
            metadata=dict(metadata or {}),
            dedupe=dedupe,
            size=len(data),
            generated=generated,
            used=list(used) if used is not None else [],
        )
        self.manifest.resources.append(record)
        return record

    def add_pointer(
        self,
        *,
        external_uri: str,
        hash_: str,
        type_: str,
        tracking_id: UUID,
        logical_key: str | None = None,
        visibility: str = "hidden",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        dedupe: bool = True,
        generated: bool = False,
        used: list[BundleUsedRef] | None = None,
    ) -> BundleResource:
        """Append a ``kind="pointer"`` manifest record: write **no** bytes.

        An external pointer is a resource the platform must not re-host, so there
        is no content-addressed byte file, the record carries the ``external_uri``
        and the canonical ``hash`` replay re-registers under.  ``hash_`` is
        validated as a canonical ``sha256:<hex>`` (the same shape a managed hash
        takes), raising :class:`ValueError` otherwise.  Returns the appended
        :class:`BundleResource`.
        """
        _sha256_hex(hash_)  # validate canonical shape. Pointers carry no byte file
        record = BundleResource(
            tracking_id=tracking_id,
            hash=hash_,
            type=type_,
            kind="pointer",
            logical_key=logical_key,
            visibility=visibility,
            tags=list(tags or []),
            metadata=dict(metadata or {}),
            dedupe=dedupe,
            external_uri=external_uri,
            generated=generated,
            used=list(used or []),
        )
        self.manifest.resources.append(record)
        return record

    def resource_bytes(self, record: BundleResource) -> bytes:
        """Read back the recorded bytes for ``record`` from ``resources/``.

        Routes through :func:`resource_filename`, so a non-canonical ``hash`` in
        a crafted manifest raises :class:`ValueError` rather than reading a
        traversed path outside ``resources/``.
        """
        byte_path = self.resources_dir / resource_filename(record.hash, record.type)
        return byte_path.read_bytes()

    def write(self) -> None:
        """Flush the manifest to ``manifest.lock`` (deterministic YAML)."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_bytes(_dump_sorted_yaml(self.manifest))

    @classmethod
    def read(cls, root: Path) -> Bundle:
        """Load an existing bundle directory.

        Within the supported major, the manifest is parsed tolerantly
        (``extra="ignore"``) so a bundle written by a later *minor* still loads,
        keeping only the fields this schema models.  A newer *major* is refused
        (:class:`ValueError`) rather than reinterpreted under the current
        semantics.
        """
        raw: dict[str, Any] = yaml.safe_load((root / MANIFEST_NAME).read_bytes()) or {}
        _check_schema_major(raw)
        manifest = BundleManifest.model_validate(raw)
        return cls(root=root, manifest=manifest)


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "MANIFEST_NAME",
    "RESOURCES_DIRNAME",
    "Bundle",
    "BundleActivity",
    "BundleBook",
    "BundleBookEntry",
    "BundleManifest",
    "BundleResource",
    "BundleUsedRef",
    "compute_book_bundle_hash",
    "resource_filename",
    "synthesise_pointer_hash",
]
