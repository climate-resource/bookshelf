"""Tests that ``Bundle.validate`` refuses a manifest edited by hand after it was recorded."""

import os
import re
import tracemalloc
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest

from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import BookshelfError
from bookshelf._core.hashing import sha256_hex
from bookshelf._produce.provenance import canonical_config_hash, derive_activity_id
from bookshelf.cache import ContentCache
from bookshelf.publisher.bundle import (
    Bundle,
    BundleActivity,
    BundleBook,
    InvalidBundleError,
    resource_filename,
)
from bookshelf.publisher.recording import RecordingSink
from tests.conftest import BundleFactory

CODE_REF = "https://github.com/example/lab.git@" + "a" * 40


def _book(**fields: str) -> BundleBook:
    framing = {"volume": "example", "version": "v1.0.0", "license": "MIT", **fields}
    return BundleBook(**framing, processing=[])


def _with_activity(bundle: Bundle, *, activity_id: uuid.UUID | None = None) -> BundleActivity:
    parameters = {"year": 2024}
    config_hash = canonical_config_hash(parameters)
    activity = BundleActivity(
        activity_id=activity_id
        or derive_activity_id(
            kind="run", code_ref=CODE_REF, config_hash=config_hash, parameters=parameters
        ),
        kind="run",
        code_ref=CODE_REF,
        config_hash=config_hash,
        parameters=parameters,
    )
    bundle.set_activity(activity)
    bundle.require_framing().processing = [(CODE_REF, config_hash)]
    return activity


def _reread(bundle: Bundle) -> Bundle:
    bundle.write()
    return Bundle.read(bundle.root)


def test_a_duplicate_resource_name_is_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle(entries=2)
    bundle.manifest.resources[1].name = bundle.manifest.resources[0].name

    with pytest.raises(InvalidBundleError, match="resource name 'entry-0' is recorded twice"):
        _reread(bundle).validate()


def test_a_duplicate_book_entry_is_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle(entries=2)
    bundle.require_framing().entries[1].name = "entry-0"

    with pytest.raises(InvalidBundleError, match="book entry 'entry-0' appears twice"):
        _reread(bundle).validate()


@pytest.mark.parametrize("delta", [1, -1])
def test_an_edited_size_is_refused(make_bundle: BundleFactory, delta: int) -> None:
    bundle = make_bundle()
    resource = bundle.manifest.resources[0]
    assert resource.size is not None
    resource.size += delta

    with pytest.raises(InvalidBundleError, match=r"records size \d+, but its bytes are \d+"):
        _reread(bundle).validate()


def test_an_unknown_book_visibility_is_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    bundle.require_framing().visibility = "topsecret"
    bundle.write()

    with pytest.raises(InvalidBundleError, match=r"book\.visibility"):
        Bundle.read(bundle.root)


@pytest.mark.parametrize(
    ("volume", "reason"),
    [
        ("v" * 101, "at most 100"),
        ("Bad Name With Spaces/ünï", "letters, digits"),
        ("latest", "reserved"),
        ("", "letters, digits"),
    ],
    ids=["too-long", "charset", "reserved", "empty"],
)
def test_an_unusable_volume_name_is_refused(
    make_bundle: BundleFactory, volume: str, reason: str
) -> None:
    bundle = make_bundle(book=_book(volume=volume))

    with pytest.raises(InvalidBundleError, match=f"volume {volume!r}.*{reason}"):
        bundle.validate()


@pytest.mark.parametrize(
    "version",
    ["v" * 51, "../../etc", "v1 0", "", ".", "v1/2", "-v1"],
    ids=["too-long", "traversal", "space", "empty", "dot", "slash", "leading-dash"],
)
def test_an_unusable_book_version_is_refused(make_bundle: BundleFactory, version: str) -> None:
    bundle = make_bundle(book=_book(version=version))

    with pytest.raises(InvalidBundleError, match=f"version {version!r}"):
        bundle.validate()


@pytest.mark.parametrize("version", ["v1.0.0", "2023-10", "v20231116", "v1.0.0-rc.1+build.5"])
def test_a_usable_book_version_validates(make_bundle: BundleFactory, version: str) -> None:
    make_bundle(book=_book(version=version)).validate()


def test_a_recorded_activity_validates(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    _with_activity(bundle)

    _reread(bundle).validate()


def test_an_activity_with_an_explicit_id_validates(make_bundle: BundleFactory) -> None:
    """A producer may name its activity, so only a hash that nothing vouches for is refused."""
    bundle = make_bundle()
    _with_activity(bundle, activity_id=uuid.uuid4())

    _reread(bundle).validate()


def test_processing_that_does_not_match_the_activity_is_refused(
    make_bundle: BundleFactory,
) -> None:
    bundle = make_bundle()
    _with_activity(bundle)
    bundle.require_framing().processing = [("x", "y")]

    with pytest.raises(InvalidBundleError, match="processing .* does not match the activity"):
        _reread(bundle).validate()


def test_processing_without_an_activity_is_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    bundle.require_framing().processing = [(CODE_REF, "sha256:" + "0" * 64)]

    with pytest.raises(InvalidBundleError, match="processing .* does not match the activity"):
        _reread(bundle).validate()


def test_an_edited_config_hash_is_refused(make_bundle: BundleFactory) -> None:
    """The tamper edits both the activity and the processing, so the two still agree."""
    bundle = make_bundle()
    activity = _with_activity(bundle)
    forged = "sha256:" + "0" * 64
    activity.config_hash = forged
    bundle.require_framing().processing = [(CODE_REF, forged)]

    with pytest.raises(InvalidBundleError, match="config_hash .* is not the digest"):
        _reread(bundle).validate()


def test_edited_parameters_are_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    activity = _with_activity(bundle)
    activity.parameters = {"year": 1990}

    with pytest.raises(InvalidBundleError, match="config_hash .* is not the digest"):
        _reread(bundle).validate()


def test_a_managed_resource_rewritten_as_a_pointer_is_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    resource = bundle.manifest.resources[0]
    resource.kind = "pointer"
    resource.external_uri = "https://example.invalid/data.csv"
    resource.size = None

    with pytest.raises(InvalidBundleError, match="pointer .* has bytes in the bundle"):
        _reread(bundle).validate()


def test_a_pointer_carrying_a_size_is_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    resource = bundle.manifest.resources[0]
    resource.kind = "pointer"
    resource.external_uri = "https://example.invalid/data.csv"
    bundle.write()

    with pytest.raises(InvalidBundleError, match="pointer resource carries no size"):
        Bundle.read(bundle.root)


def _pointer_bundle(tmp_path: Path, uri: str) -> Bundle:
    """A recorded pointer bundle whose target is then edited by hand to ``uri``."""
    bundle = Bundle(tmp_path / "bundle")
    bundle.set_book(_book())
    bundle.add_pointer(
        external_uri="https://example.com/data.csv",
        hash_=sha256_hex(b"x"),
        type_="tabular",
        name="ptr",
    )
    bundle.add_book_entry(name="ptr")
    bundle.mark_book_published()
    bundle.manifest.resources[0].external_uri = uri
    return bundle


_REFUSED_POINTERS = {
    "file": "file:///etc/passwd",
    "bare-path": "/etc/passwd",
    "http": "http://example.com/data.csv",
    "s3": "s3://bucket/key",
    "no-host": "https:///no-host",
    "loopback": "https://127.0.0.1/data.csv",
    "control": "https://example.com/\ndata.csv",
    "hex": "https://0x7f000001/data.csv",
    "decimal": "https://2130706433/data.csv",
    "short": "https://127.1/data.csv",
    "octal": "https://0177.0.0.1/data.csv",
    "localhost": "https://localhost/data.csv",
    "localhost-dot": "https://localhost./data.csv",
    "localhost-sub": "https://api.localhost/data.csv",
    "loopback-dot": "https://127.0.0.1./data.csv",
    "mapped": "https://[::ffff:127.0.0.1]/data.csv",
    "fullwidth": "https://\uff11\uff12\uff17.0.0.1/data.csv",
    "bad-octal": "https://08.0.0.1/data.csv",
    "percent": "https://%31%32%37.0.0.1/data.csv",
    "ideographic-dots": "https://127\u30020\u30020\u30021/data.csv",
    "localhost-ideographic": "https://localhost\u3002/data.csv",
    "halfwidth-dots": "https://127\uff610\uff610\uff611/data.csv",
}


@pytest.mark.parametrize("uri", _REFUSED_POINTERS.values(), ids=_REFUSED_POINTERS.keys())
def test_a_pointer_the_platform_would_refuse_is_refused(tmp_path: Path, uri: str) -> None:
    bundle = _pointer_bundle(tmp_path, uri)

    with pytest.raises(InvalidBundleError, match="pointer 'ptr'"):
        bundle.validate()


@pytest.mark.parametrize("uri", _REFUSED_POINTERS.values(), ids=_REFUSED_POINTERS.keys())
def test_a_pointer_the_platform_would_refuse_is_never_recorded(tmp_path: Path, uri: str) -> None:
    bundle = Bundle(tmp_path / "bundle")

    with pytest.raises(BookshelfError, match="ptr"):
        bundle.add_pointer(external_uri=uri, hash_=sha256_hex(b"x"), type_="tabular", name="ptr")

    assert bundle.manifest.resources == []


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/data.csv",
        "https://example.com./data.csv",
        "https://8.8.8.8/data.csv",
        "https://deadbeef.example/data.csv",
        "rdm://dataset/primap-hist@v2.8",
    ],
    ids=str,
)
def test_a_pointer_the_platform_accepts_validates(tmp_path: Path, uri: str) -> None:
    bundle = Bundle(tmp_path / "bundle")
    bundle.set_book(_book())
    bundle.add_pointer(external_uri=uri, hash_=sha256_hex(b"x"), type_="tabular", name="ptr")
    bundle.add_book_entry(name="ptr")
    bundle.mark_book_published()

    bundle.validate()


def _escape(bundle: Bundle, tmp_path: Path) -> Path:
    """Move the first resource's bytes outside the bundle and leave a symlink in their place."""
    resource = bundle.manifest.resources[0]
    inside = bundle.resources_dir / resource_filename(resource.hash, resource.type)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(inside.read_bytes())
    inside.unlink()
    inside.symlink_to(outside)
    return inside


def test_a_symlink_escaping_the_bundle_is_refused(
    make_bundle: BundleFactory, tmp_path: Path
) -> None:
    """The hash still matches, so only the location gives the edit away."""
    bundle = make_bundle()
    _escape(bundle, tmp_path)

    with pytest.raises(InvalidBundleError, match="outside the bundle"):
        bundle.validate()


def test_reading_bytes_through_an_escaping_symlink_is_refused(
    make_bundle: BundleFactory, tmp_path: Path
) -> None:
    """Replay reads the bytes it uploads through the same guard."""
    bundle = make_bundle()
    _escape(bundle, tmp_path)

    with pytest.raises(InvalidBundleError, match="outside the bundle"):
        bundle.resource_bytes(bundle.manifest.resources[0])


def test_a_symlink_inside_the_bundle_validates(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    resource = bundle.manifest.resources[0]
    inside = bundle.resources_dir / resource_filename(resource.hash, resource.type)
    moved = bundle.root / "elsewhere.bin"
    inside.rename(moved)
    inside.symlink_to(moved)

    bundle.validate()


def test_validate_hashes_in_chunks(tmp_path: Path) -> None:
    """Peak memory must not grow with the largest resource."""
    data = b"\0" * (32 << 20)
    bundle = Bundle(tmp_path / "bundle")
    bundle.set_book(_book())
    bundle.add_resource(data=data, hash_=sha256_hex(data), type_="document", name="big")
    bundle.add_book_entry(name="big")
    bundle.mark_book_published()
    del data

    tracemalloc.start()
    try:
        bundle.validate()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 8 << 20


def test_a_schema_error_names_the_field_without_the_pydantic_link(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "manifest.lock").write_text(
        "schema_version: '3.10'\nresources:\n- name: a\n  hash: x\n  type: document\n  size: big\n"
    )

    with pytest.raises(InvalidBundleError) as raised:
        Bundle.read(root)

    message = str(raised.value)
    assert "resources.0.size" in message
    assert "errors.pydantic.dev" not in message
    assert "\n" not in message


def test_a_newer_major_names_the_upgrade_as_its_remedy(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "manifest.lock").write_text("schema_version: '4.0'\nresources: []\n")

    with pytest.raises(InvalidBundleError) as raised:
        Bundle.read(root)

    assert not str(raised.value).endswith(".")
    assert raised.value.remedy == "Upgrade bookshelf to read it."


def test_recording_refuses_an_activity_that_nothing_vouches_for(tmp_path: Path) -> None:
    """Validate would refuse it, so the recorder refuses it first."""
    sink = RecordingSink(
        Bundle(tmp_path / "bundle"), Mock(spec=BookshelfClient), ContentCache(tmp_path / "cache")
    )

    with pytest.raises(BookshelfError, match="activity_id or config_hash"):
        sink.activity(
            code_ref=CODE_REF,
            config={"year": 2024},
            activity_id=uuid.uuid4(),
            config_hash="sha256:" + "1" * 64,
        )


@pytest.mark.parametrize(
    "uri", ["https://[::1/data.csv", "https://example.com:port/data.csv"], ids=["ipv6", "port"]
)
def test_a_malformed_pointer_url_is_an_invalid_bundle(tmp_path: Path, uri: str) -> None:
    bundle = _pointer_bundle(tmp_path, uri)

    with pytest.raises(InvalidBundleError, match="pointer 'ptr'"):
        bundle.validate()


def test_a_fifo_in_place_of_resource_bytes_is_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    resource = bundle.manifest.resources[0]
    path = bundle.resources_dir / resource_filename(resource.hash, resource.type)
    path.unlink()
    os.mkfifo(path)

    with pytest.raises(InvalidBundleError, match="not a regular file"):
        bundle.validate()


def test_a_fifo_in_place_of_the_manifest_is_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    bundle.manifest_path.unlink()
    os.mkfifo(bundle.manifest_path)

    with pytest.raises(InvalidBundleError, match="not a regular file"):
        Bundle.read(bundle.root)


@pytest.mark.parametrize("edit", ["  size: null\n", ""], ids=["null", "missing"])
def test_a_managed_resource_without_a_size_is_refused(
    make_bundle: BundleFactory, edit: str
) -> None:
    bundle = make_bundle()
    text = bundle.manifest_path.read_text(encoding="utf-8")
    edited = re.sub(r"  size: \d+\n", edit, text)
    assert edited != text
    bundle.manifest_path.write_text(edited, encoding="utf-8")

    with pytest.raises(InvalidBundleError, match="records no size"):
        Bundle.read_validated(bundle.root)


@pytest.mark.parametrize("edit", ["  processing: null\n", ""], ids=["null", "missing"])
def test_a_book_without_processing_is_refused(make_bundle: BundleFactory, edit: str) -> None:
    bundle = make_bundle()
    text = bundle.manifest_path.read_text(encoding="utf-8")
    edited = text.replace("  processing: []\n", edit)
    assert edited != text
    bundle.manifest_path.write_text(edited, encoding="utf-8")

    with pytest.raises(InvalidBundleError, match="records no processing"):
        Bundle.read_validated(bundle.root)


@pytest.mark.parametrize(
    ("anchor", "added", "where"),
    [
        ("schema_version:", "visiblity: public\n", "visiblity"),
        ("  volume: example\n", "  visiblity: public\n", "book.visiblity"),
        ("  - name: entry-0\n", "    visiblity: public\n", "book.entries[0].visiblity"),
        ("- generated: false\n", "  visiblity: public\n", "resources[0].visiblity"),
    ],
    ids=["top", "book", "entry", "resource"],
)
def test_an_unknown_manifest_key_is_refused(
    make_bundle: BundleFactory, anchor: str, added: str, where: str
) -> None:
    bundle = make_bundle()
    text = bundle.manifest_path.read_text(encoding="utf-8")
    assert anchor in text
    edited = text.replace(anchor, added + anchor if anchor.endswith(":") else anchor + added, 1)
    bundle.manifest_path.write_text(edited, encoding="utf-8")

    with pytest.raises(InvalidBundleError, match=re.escape(where)):
        Bundle.read_validated(bundle.root)


def test_an_unknown_key_from_a_newer_minor_still_validates(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    text = bundle.manifest_path.read_text(encoding="utf-8")
    edited = re.sub(r"schema_version: '?[\d.]+'?", "schema_version: '3.999'\nlater: 1", text)
    bundle.manifest_path.write_text(edited, encoding="utf-8")

    Bundle.read_validated(bundle.root)


def test_an_unknown_author_key_is_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    text = bundle.manifest_path.read_text(encoding="utf-8")
    edited = text.replace(
        "- generated: false\n",
        "- authors:\n  - name: Ada\n    affilitation: Institute\n  generated: false\n",
        1,
    )
    bundle.manifest_path.write_text(edited, encoding="utf-8")

    with pytest.raises(InvalidBundleError, match=re.escape("resources[0].authors[0].affilitation")):
        Bundle.read_validated(bundle.root)


def test_a_retired_dedupe_from_an_older_minor_still_validates(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    text = bundle.manifest_path.read_text(encoding="utf-8")
    edited = text.replace("- generated: false\n", "- dedupe: true\n  generated: false\n", 1)
    edited = re.sub(r"schema_version: '?[\d.]+'?", "schema_version: '3.9'", edited)
    bundle.manifest_path.write_text(edited, encoding="utf-8")

    Bundle.read_validated(bundle.root)


def test_dedupe_in_a_current_manifest_is_refused(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    text = bundle.manifest_path.read_text(encoding="utf-8")
    edited = text.replace("- generated: false\n", "- dedupe: true\n  generated: false\n", 1)
    bundle.manifest_path.write_text(edited, encoding="utf-8")

    with pytest.raises(InvalidBundleError, match=re.escape("resources[0].dedupe")):
        Bundle.read_validated(bundle.root)
