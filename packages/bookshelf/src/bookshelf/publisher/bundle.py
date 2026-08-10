"""The bundle: an on-disk, replayable record of a run, using manifest schema v1.

A bundle holds a manifest and the content-addressed bytes of every managed resource,
so it is self-contained.
It can be produced, reviewed and validated with no server involved,
and replayed byte-for-byte when it is published.
It extends the ADR-0007 lock, and it is pre-edition:
the server assigns the edition during replay.

The bytes on disk are specified in ``docs/explanation/bundle-format.md``.
That document is the contract, and an implementation in another language is written against it.
This module implements it:

- :class:`Bundle` owns the directory, its ``resources/`` bytes, and the reads and writes over both.
- The ``Bundle*`` models mirror the manifest structure field for field.
  Each uses ``extra="ignore"``, which is the forward-compatibility contract.
  A manifest from a newer *minor* loads and keeps the fields this version models.
  :meth:`Bundle.read` refuses a newer *major* rather than reinterpreting it.
- :meth:`Bundle.validate` asserts the rules that decide whether a bundle is a replayable
  published book, because the bundle already holds everything those rules need.
  It raises :class:`InvalidBundleError`,
  so every caller refuses the same bundles for the same reasons.

Serialisation is deterministic:
sorted keys,
LF newlines,
and no timestamps.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bookshelf._core.errors import BookshelfError
from bookshelf._core.hashing import canonical_json_bytes, sha256_hex
from bookshelf._generated import models

BUNDLE_SCHEMA_VERSION = "1.1"

# The major this reader models.
# A newer *minor* is additive and loads
# because the models ignore unknown fields.
# A newer *major* signals a breaking change.
# Reading it under v1 semantics would drop fields that carry new meaning.
_SUPPORTED_SCHEMA_MAJOR = int(BUNDLE_SCHEMA_VERSION.split(".", 1)[0])

MANIFEST_NAME = "manifest.lock"
RESOURCES_DIRNAME = "resources"

# Map a resource ``type`` to the byte-file extension under ``resources/``.
# Mirrors ``serialise.py``: parquet for the frame types, opaque otherwise.
_PARQUET_TYPES = frozenset({"timeseries", "tabular"})

# A canonical resource hash is ``sha256:`` + exactly 64 lowercase hex chars.
# Validate against this before deriving a byte-file name.
# The path component then remains a clean digest
# with no ``:``, ``/``, or ``.`` characters.
# A crafted manifest hash therefore cannot traverse out of ``resources/``.
_SHA256_RE = re.compile(r"^sha256:([0-9a-f]{64})$")


class InvalidBundleError(BookshelfError):
    """A bundle on disk breaks the contract a bundle promises.

    The message names the invariant that failed
    and carries the detail a caller needs to render it.
    A caller therefore either holds a bundle that keeps its contract
    or holds an error explaining why it does not.
    """


def _sha256_hex(hash_: str) -> str:
    """Return the 64-char hex digest of a canonical ``sha256:<hex>`` hash.

    Raises :class:`ValueError`
    unless the value is exactly ``sha256:``
    followed by 64 lowercase hex characters.
    The result is therefore safe to use as a filesystem path component.
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
    The reference is recorded as the run expressed it,
    and it is resolved again when the bundle is replayed.
    A recorded ``tracking_id`` is rewritten client-side
    to the id the server returned for that input,
    because the server may answer a registration
    with a resource it already holds.
    A ``logical_key`` is resolved by the server at registration time.
    The recorded reference is therefore the run's claim about its inputs,
    not the identity of the edge the backend finally mints.

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


# The shelf slug through which the backend funnels an ``external_uri``
# before synthesising a hash:
# ``LocationInput(shelf="external", path=external_uri)``.
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
    seed = canonical_json_bytes(
        {
            "type": type_,
            "logical_key": logical_key or "",
            "locations": locations,
        }
    )
    return sha256_hex(seed)


class BundleResource(BaseModel):
    """One resource recorded in the bundle manifest.

    ``hash`` is the canonical pre-edition ``sha256:<hex>`` value.
    It drives replay registration idempotency.
    ``kind`` is the **explicit** discriminator between two variants:

    - ``"managed"``:
      the platform re-hosts the bytes.
      ``hash`` is the digest of the bytes at ``resources/<hex>.<ext>``.
      ``size`` is their length.
      For an activity output,
      ``generated`` marks the output
      and ``used`` carries its lineage input references.
    - ``"pointer"``:
      an external pointer created with ``register_external``.
      ``external_uri`` is the target that the platform must not re-host.
      There is no byte file,
      and ``size`` is omitted.

    ``extra="ignore"`` keeps each resource record forward-compatible.
    A later book-framing slice can add fields such as ``name_in_book``.
    An older reader still loads that record
    by dropping fields it does not model.
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

    Mirrors the wire :class:`~bookshelf._generated.models.ActivityEnvelope`,
    minus build-level ``used`` references,
    which are recorded per resource.
    It contains the client-minted ``activity_id``
    and the descriptive fields.
    Replay creates the activity under this exact ``activity_id``.
    A repeated replay therefore finds the activity already present
    and mints no duplicate provenance edges.

    ``extra="ignore"`` tolerates fields added by a later client.
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

    ``tracking_id`` references a managed resource or pointer
    recorded in the same manifest.
    ``name_in_book`` is the stable name
    that the resource takes inside the book.
    ``data_dictionary`` describes this entry's columns.
    ``None`` records omission so replay preserves an existing dictionary,
    while an empty list records an explicit clear.
    This pair feeds the bundle-hash seal
    as a sorted ``[name_in_book, sha256_hex]`` member.
    It is both the unit replay attaches
    and the unit used to compute the idempotency key.

    ``extra="ignore"`` tolerates fields added by a later client.
    """

    model_config = ConfigDict(extra="ignore")

    name_in_book: str
    tracking_id: UUID
    data_dictionary: list[dict[str, Any]] | None = None


class BundleBook(BaseModel):
    """The book framing recorded in the bundle manifest (pre-edition).

    Mirrors the producer's
    ``create_draft_book -> attach_entry* -> publish`` arc.
    ``volume``,
    ``version``,
    ``visibility``,
    and ``license`` frame the draft.
    ``entries`` carries the ``name_in_book -> resource`` membership.
    ``published`` records whether replay should publish the draft
    or leave it as a draft.
    ``authors`` and ``discovery`` carry the editorial framing the recipe resolved for this version,
    and replay sends both on the draft call
    so each book keeps its own copy of what was true when it was published.
    Publishing a later version therefore never rewrites what an earlier one says.
    Neither enters the seal,
    which stays byte-identical to the platform's over membership alone.

    ``discovery`` is keyed by the recipe's own field names.
    The API spells one of them differently,
    and that is reconciled where the draft request is built.

    The framing is **pre-edition**
    and has no ``edition`` field.
    The server assigns the edition during replay under ADR 0006.
    Replay keys the draft on the content bundle hash
    computed from this framing.
    Two replays of the same bundle therefore converge on one edition.
    ``extra="ignore"`` tolerates fields added by a later client.
    """

    model_config = ConfigDict(extra="ignore")

    volume: str
    version: str
    visibility: str = "hidden"
    license: str | None = None
    authors: list[dict[str, Any]] = Field(default_factory=list)
    discovery: dict[str, Any] | None = None
    description: str | None = None
    citation_doi: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    entries: list[BundleBookEntry] = Field(default_factory=list)
    published: bool = False


def _pyarrow_version() -> str | None:
    """Return the installed pyarrow version, or ``None`` when it is not installed.

    pyarrow arrives with the optional extras,
    so a bundle can legitimately be written on a machine without it.
    The version is read from the installed distribution metadata
    rather than by importing pyarrow,
    because the import is slow and the package may be absent.
    """
    try:
        return importlib.metadata.version("pyarrow")
    except importlib.metadata.PackageNotFoundError:
        return None


class BundleWriter(BaseModel):
    """The library versions that produced the bytes under ``resources/``.

    Parquet output is not stable across pyarrow versions,
    so the same frame written by two pyarrow versions has two content hashes.
    Recording the writer version makes that difference explain itself,
    rather than surfacing as an unattributed change in the recorded hashes.

    ``extra="ignore"`` tolerates fields added by a later client.
    """

    model_config = ConfigDict(extra="ignore")

    pyarrow: str | None = None


class BundleManifest(BaseModel):
    """The bundle's ``manifest.lock`` document.

    Carries the schema version,
    the optional ``writer`` header,
    the optional ``activity`` envelope,
    the optional ``book`` framing,
    and the managed ``resources``.
    ``model_config`` uses ``extra="ignore"``.
    A manifest written by a later minor version therefore still loads,
    while fields this version does not model are dropped.
    This is the tracer's forward-compatibility contract.
    :meth:`Bundle.read` refuses a newer major before validation
    instead of reinterpreting it here.

    ``activity`` is ``None`` for a managed-only bundle.
    ``book`` is ``None`` for a resources-only bundle.
    Each extension is therefore additive.
    A bundle without them loads and replays
    exactly as it did before the extension landed.
    """

    # Tolerant of added fields:
    # later slices extend the manifest,
    # and an older reader must still load a newer bundle.
    model_config = ConfigDict(extra="ignore")

    schema_version: str = BUNDLE_SCHEMA_VERSION
    writer: BundleWriter | None = None
    activity: BundleActivity | None = None
    book: BundleBook | None = None
    resources: list[BundleResource] = Field(default_factory=list)


def _check_schema_major(raw: dict[str, Any]) -> None:
    """Refuse a manifest whose major schema version this reader cannot model.

    A newer minor is forward-compatible.
    The models ignore unknown fields,
    so an additive change still loads.
    A newer major signals a breaking change.
    Loading it under the current semantics
    could silently drop fields that carry new meaning.
    Raise rather than misinterpret the bundle.
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

    Validates that ``hash_`` is a canonical ``sha256:<hex>``.
    Raises :class:`ValueError` otherwise.
    The result uses the bare 64-character digest
    plus a type-derived extension.
    ``resources/`` is therefore keyed purely on content,
    and a crafted hash cannot escape the directory.
    """
    hex_digest = _sha256_hex(hash_)
    extension = "parquet" if type_ in _PARQUET_TYPES else "bin"
    return f"{hex_digest}.{extension}"


def compute_book_bundle_hash(manifest: BundleManifest) -> str:
    """Return the content bundle hash for the manifest's book framing.

    This mirrors the backend ``_compute_bundle_hash`` seal
    and **must** stay byte-identical to it.
    The seal is the draft idempotency key.
    Any drift makes replay mint a fresh edition
    or fail the publish recompute assertion.
    Canonicalisation uses one canonical JSON document,
    sorted keys,
    ``(",", ":")`` separators,
    and :func:`~bookshelf._core.hashing.canonical_json_bytes`:

    - ``license``:
      the book's SPDX license,
      or ``None`` when unset.
    - ``members``:
      the **sorted** list of ``[name_in_book, sha256_hex]`` pairs.
      ``sha256_hex`` is the validated 64-character lowercase digest
      of each member resource's canonical ``sha256:<hex>`` hash.
    - ``visibility``: the book's three-tier visibility value.

    Each entry's resource is resolved from the manifest by ``tracking_id``.
    The digest is the 64-character lowercase value
    without the ``sha256:`` prefix.
    This matches the backend's ``hexdigest()``
    and the ``bundle_hash`` wire field.

    Raises :class:`ValueError`
    if the manifest has no book framing,
    an entry references an unrecorded resource,
    or a member resource has no canonical SHA256 hash.
    Any of those states would make the seal ambiguous.
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


def _sort_recursive(obj: Any) -> Any:  # noqa: ANN401
    """Recursively sort every mapping by key, preserving list order."""
    if isinstance(obj, dict):
        return {k: _sort_recursive(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_sort_recursive(item) for item in obj]
    return obj


def _dump_sorted_yaml(model: BaseModel) -> bytes:
    """Serialise a manifest model to deterministic YAML bytes (LF, UTF-8).

    Output is byte-identical across runs with unchanged inputs.
    It omits ``None`` values,
    sorts every mapping by key,
    preserves list order,
    carries no timestamps,
    and never line-wraps.
    """
    text = yaml.dump(
        _sort_recursive(model.model_dump(mode="json", exclude_none=True)),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
        width=10000,  # do not line-wrap long strings
    )
    # The manifest is LF regardless of the platform it was written on.
    normalised = str(text).replace("\r\n", "\n").replace("\r", "\n")
    return normalised.encode("utf-8")


class Bundle:
    """A bundle directory on disk: the manifest plus ``resources/`` bytes.

    Construct one over a possibly empty directory.
    :meth:`add_resource` writes a content-addressed byte file
    and appends a manifest record.
    :meth:`write` flushes the manifest.
    :meth:`read` loads an existing bundle.

    A bundle also owns the rules that decide whether it is a replayable published book.
    :meth:`validate` asserts the whole contract,
    :meth:`require_framing` asserts the framing alone,
    and :meth:`read_validated` reads and asserts in one call.
    Each raises :class:`InvalidBundleError`,
    so a caller never has to rediscover a rule the bundle already knows.
    """

    def __init__(self, root: Path, manifest: BundleManifest | None = None) -> None:
        self.root = root
        # A fresh bundle records the writer versions of the machine writing it,
        # and the whole block is absent when pyarrow is not installed.
        # A manifest handed in came from disk, so it keeps whatever header it was written with.
        if manifest is None:
            version = _pyarrow_version()
            manifest = BundleManifest(
                writer=BundleWriter(pyarrow=version) if version is not None else None
            )
        self.manifest = manifest

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

        A bundle represents one build.
        Recording a second envelope that differs in any field
        is therefore a programming error
        and raises :class:`ValueError`.
        Recording the *identical* envelope again is a no-op.
        """
        if self.manifest.activity is not None:
            if self.manifest.activity != activity:
                raise ValueError("bundle already has a different activity recorded")
            return
        self.manifest.activity = activity

    def set_book(self, book: BundleBook) -> None:
        """Record the book framing on the manifest (one book per bundle).

        A bundle records one book's draft,
        attach,
        and publish arc.
        A second ``set_book`` therefore raises :class:`ValueError`.
        :meth:`add_book_entry` appends entries later.
        :meth:`mark_book_published` flips the publish flag.
        Both mutate the framing recorded here.
        """
        if self.manifest.book is not None:
            raise ValueError("bundle already has a book recorded")
        self.manifest.book = book

    def add_book_entry(
        self,
        *,
        name_in_book: str,
        tracking_id: UUID,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
    ) -> BundleBookEntry:
        """Append a ``name_in_book -> resource`` entry to the recorded book.

        ``tracking_id`` must reference a resource
        already recorded in this manifest.
        ``data_dictionary`` belongs to this attachment rather than the book framing.
        Omit it to preserve an existing entry dictionary,
        or pass an empty sequence to clear one.
        The bundle therefore stays self-contained,
        and its membership always determines the bundle hash.
        ``name_in_book`` must be unique within the book.
        The backend enforces the same constraint.
        A duplicate raises :class:`ValueError` here
        instead of failing during replay.
        The method also raises :class:`ValueError`
        if no book has been drafted.
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
        entry = BundleBookEntry(
            name_in_book=name_in_book,
            tracking_id=tracking_id,
            data_dictionary=(
                None
                if data_dictionary is None
                else [item.model_dump(mode="json") for item in data_dictionary]
            ),
        )
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

        The byte file is named from the content-addressed ``hash_``.
        Recording the same bytes twice is therefore a no-op write.
        Returns the appended :class:`BundleResource`.

        ``generated`` and ``used`` carry lineage
        when the resource was produced inside an activity.
        ``generated`` marks it as an activity output.
        ``used`` records the input references verbatim.
        Both default to the no-lineage case,
        so a plain managed registration retains its earlier shape.

        ``hash_`` must be the canonical ``sha256:<hex>`` of ``data``.
        The digest is recomputed and verified before any write.
        A mismatch raises :class:`ValueError`.
        The content-addressed name therefore always matches the bytes.
        The happy path already has this property
        because the hash comes from the shared serialiser.
        The check is defence in depth against a forged hash.
        """
        expected = sha256_hex(data)
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

        The platform must not re-host an external pointer.
        There is therefore no content-addressed byte file.
        The record carries ``external_uri``
        and the canonical ``hash`` used by replay.
        ``hash_`` is validated as a canonical ``sha256:<hex>``,
        which is the same shape as a managed hash.
        Invalid values raise :class:`ValueError`.
        Returns the appended :class:`BundleResource`.
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

        Routes through :func:`resource_filename`.
        A non-canonical ``hash`` in a crafted manifest
        therefore raises :class:`ValueError`
        instead of reading a traversed path outside ``resources/``.
        """
        byte_path = self.resources_dir / resource_filename(record.hash, record.type)
        return byte_path.read_bytes()

    def require_framing(self) -> BundleBook:
        """Return the recorded book framing, or raise :class:`InvalidBundleError`.

        A resources-only bundle records no book,
        so replay has nothing to draft.
        """
        if self.manifest.book is None:
            raise InvalidBundleError("bundle has no book framing")
        return self.manifest.book

    def validate(self) -> None:
        """Assert this bundle is a replayable published book.

        The contract is:

        - the bundle records a book framing
        - that book is marked for publication
        - the book has at least one entry
        - every entry references a resource recorded in the same manifest
        - every managed resource's bytes are present and still hash to the recorded hash,
          which a non-canonical hash cannot satisfy because it names no byte file

        The bytes are re-hashed rather than trusted,
        so a bundle edited between record and replay is refused here
        instead of publishing content that no reviewer saw.
        Raises :class:`InvalidBundleError` naming the first invariant that fails.
        """
        framing = self.require_framing()
        if not framing.published:
            raise InvalidBundleError("bundle does not record a publish operation")
        if not framing.entries:
            raise InvalidBundleError("bundle has no book entries")

        recorded = {resource.tracking_id for resource in self.manifest.resources}
        for entry in framing.entries:
            if entry.tracking_id not in recorded:
                raise InvalidBundleError(f"book entry {entry.name_in_book!r} has no resource")

        for resource in self.manifest.resources:
            if resource.kind != "managed":
                continue
            try:
                data = self.resource_bytes(resource)
            except ValueError as exc:
                raise InvalidBundleError(
                    f"resource {resource.tracking_id} has a non-canonical hash {resource.hash!r}"
                ) from exc
            except OSError as exc:
                raise InvalidBundleError(
                    f"resource {resource.tracking_id} has no bytes in the bundle: {exc}"
                ) from exc
            actual = sha256_hex(data)
            if actual != resource.hash:
                raise InvalidBundleError(
                    f"resource {resource.tracking_id} has hash {resource.hash}, got {actual}"
                )

    def write(self) -> None:
        """Flush the manifest to ``manifest.lock`` (deterministic YAML)."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_bytes(_dump_sorted_yaml(self.manifest))

    @classmethod
    def read(cls, root: Path) -> Bundle:
        """Load an existing bundle directory.

        Within the supported major,
        the manifest is parsed tolerantly with ``extra="ignore"``.
        A bundle written by a later minor therefore still loads
        and keeps only the fields this schema models.
        A newer major raises :class:`ValueError`
        instead of being reinterpreted under the current semantics.

        The read is structural.
        A bundle recorded as a draft loads here and replays as a draft.
        """
        raw: dict[str, Any] = yaml.safe_load((root / MANIFEST_NAME).read_bytes()) or {}
        _check_schema_major(raw)
        manifest = BundleManifest.model_validate(raw)
        return cls(root=root, manifest=manifest)

    @classmethod
    def read_validated(cls, root: Path) -> Bundle:
        """Load a bundle directory and assert its contract in one call.

        Raises whatever :meth:`read` raises for an unreadable manifest,
        and :class:`InvalidBundleError` for a bundle that is not a replayable published book.
        """
        bundle = cls.read(root)
        bundle.validate()
        return bundle


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
    "BundleWriter",
    "InvalidBundleError",
    "compute_book_bundle_hash",
    "resource_filename",
    "synthesise_pointer_hash",
]
