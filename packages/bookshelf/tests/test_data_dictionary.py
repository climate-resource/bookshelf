"""The data dictionary a producer declares survives recording and replay."""

from pathlib import Path

from bookshelf._generated import models
from bookshelf.publisher import RecordingBookshelf
from bookshelf.publisher.bundle import Bundle, BundleBook
from bookshelf.publisher.replay import replay_bundle_sync


class _FakeDraft:
    status = "draft"

    def attach(self, resource, *, name_in_book: str) -> None:  # pragma: no cover - unused
        del resource, name_in_book

    def publish(self) -> None:  # pragma: no cover - unused
        pass


class _FakeBookshelf:
    """Captures the keyword arguments replay sends to ``draft_book``."""

    def __init__(self) -> None:
        self.draft_kwargs: dict = {}

    def draft_book(self, *_args, **kwargs) -> _FakeDraft:
        self.draft_kwargs = kwargs
        return _FakeDraft()


def test_recording_carries_the_data_dictionary_into_the_bundle(tmp_path: Path) -> None:
    """A dictionary passed at draft time is recorded in the manifest."""
    bundle = Bundle(tmp_path / "bundle")

    with RecordingBookshelf(bundle) as recording:
        book = recording.draft_book(
            "example",
            version="v1.0.0",
            license="MIT",
            data_dictionary=[
                models.DataDictionaryEntry(name="region", role="dimension"),
                models.DataDictionaryEntry(name="value", type="number", role="measure"),
            ],
        )

    assert bundle.manifest.book is not None
    recorded = bundle.manifest.book.data_dictionary
    assert [entry["name"] for entry in recorded] == ["region", "value"]
    assert recorded[1]["role"] == "measure"

    # The recording handle reports the same dictionary as a live draft handle.
    assert [entry.name for entry in book.metadata.data_dictionary] == ["region", "value"]


def test_bundle_without_a_data_dictionary_stays_empty(tmp_path: Path) -> None:
    """The field is additive: an untouched recording records an empty list."""
    bundle = Bundle(tmp_path / "bundle")

    with RecordingBookshelf(bundle) as recording:
        recording.draft_book("example", version="v1.0.0", license="MIT")

    assert bundle.manifest.book is not None
    assert bundle.manifest.book.data_dictionary == []


def test_replay_sends_the_recorded_data_dictionary(tmp_path: Path) -> None:
    """Replay forwards the recorded dictionary, so it survives the round trip."""
    bundle = Bundle(tmp_path / "bundle")
    bundle.set_book(
        BundleBook(
            volume="example",
            version="v1.0.0",
            visibility="hidden",
            license="MIT",
            data_dictionary=[{"name": "region", "type": "string", "role": "dimension"}],
        )
    )

    client = _FakeBookshelf()
    replay_bundle_sync(bundle, client)

    sent = client.draft_kwargs["data_dictionary"]
    assert [entry.name for entry in sent] == ["region"]
    assert sent[0].role == "dimension"
