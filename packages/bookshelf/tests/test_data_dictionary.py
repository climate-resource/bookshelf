"""The data dictionary a producer declares survives entry recording and replay."""

from pathlib import Path

import httpx

from bookshelf._generated import models
from bookshelf.publisher import RecordingBookshelf
from bookshelf.publisher.bundle import Bundle, BundleBook
from bookshelf.publisher.replay import replay_bundle_sync
from tests._replay import replay_client, replayed


def _pointer_bundle(
    root: Path,
    *,
    data_dictionary: list[models.DataDictionaryEntry] | None,
) -> Bundle:
    bundle = Bundle(root)
    bundle.set_book(BundleBook(volume="example", version="v1.0.0", license="MIT"))
    bundle.add_pointer(
        external_uri="https://example.invalid/data.csv",
        hash_="sha256:" + "a" * 64,
        type_="tabular",
        name="data",
    )
    bundle.add_book_entry(name="data", data_dictionary=data_dictionary)
    return bundle


def test_recording_carries_the_data_dictionary_on_the_book_entry(tmp_path: Path) -> None:
    """A dictionary declared beside an attachment is recorded on that entry."""
    bundle = Bundle(tmp_path / "bundle")

    with RecordingBookshelf(bundle) as recording:
        book = recording.draft_book("example", version="v1.0.0", license="MIT")
        resource = recording.register_external(
            type="tabular", uri="https://example.invalid/data.csv", name="data"
        )
        book.attach(
            resource,
            name_in_book="data",
            data_dictionary=[
                models.DataDictionaryEntry(name="region", role="dimension"),
                models.DataDictionaryEntry(name="value", type="number", role="measure"),
            ],
        )

    assert bundle.manifest.book is not None
    recorded = bundle.manifest.book.entries[0].data_dictionary
    assert recorded is not None
    assert [entry["name"] for entry in recorded] == ["region", "value"]
    assert recorded[1]["role"] == "measure"


def test_recording_preserves_omission_and_an_explicit_empty_dictionary(tmp_path: Path) -> None:
    omitted = _pointer_bundle(tmp_path / "omitted", data_dictionary=None)
    cleared = _pointer_bundle(tmp_path / "cleared", data_dictionary=[])

    assert omitted.manifest.book is not None
    assert omitted.manifest.book.entries[0].data_dictionary is None
    assert cleared.manifest.book is not None
    assert cleared.manifest.book.entries[0].data_dictionary == []


def test_replay_sends_the_recorded_dictionary_on_attach(tmp_path: Path) -> None:
    bundle = _pointer_bundle(
        tmp_path / "bundle",
        data_dictionary=[models.DataDictionaryEntry(name="region", role="dimension")],
    )

    recorded: list[httpx.Request] = []
    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    sent = replayed(recorded)["book"]["entries"][0]["data_dictionary"]
    assert [entry["name"] for entry in sent] == ["region"]
    assert sent[0]["role"] == "dimension"
