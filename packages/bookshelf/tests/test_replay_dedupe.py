"""End to end replay against a deployment that answers with a resource it already holds."""

from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from bookshelf._core.hashing import sha256_hex
from bookshelf.publisher.bundle import Bundle, BundleActivity, BundleBook, BundleUsedRef
from bookshelf.publisher.replay import replay_bundle_sync


class _FakeResource:
    def __init__(self, tracking_id: UUID) -> None:
        self.tracking_id = tracking_id


class _FakeActivity:
    """Stands in for a deployment that already holds the first resource's bytes."""

    def __init__(self, dedupe_to: dict[UUID, UUID], calls: list[tuple[UUID, list]]) -> None:
        self._dedupe_to = dedupe_to
        self.calls = calls

    def register(self, _data, *, tracking_id: UUID, used, **_kwargs) -> _FakeResource:
        self.calls.append((tracking_id, list(used)))
        return _FakeResource(self._dedupe_to.get(tracking_id, tracking_id))


class _FakeDraft:
    status = "draft"

    def __init__(self) -> None:
        self.attached: list[UUID] = []
        self.published = False

    def attach(self, resource, *, name_in_book: str) -> None:
        del name_in_book
        self.attached.append(resource.tracking_id)

    def publish(self) -> None:
        self.published = True


class _FakeBookshelf:
    def __init__(self, dedupe_to: dict[UUID, UUID]) -> None:
        self.draft = _FakeDraft()
        self.calls: list[tuple[UUID, list]] = []
        self._dedupe_to = dedupe_to

    def draft_book(self, *_args, **_kwargs) -> _FakeDraft:
        return self.draft

    @contextmanager
    def activity(self, **_kwargs):
        yield _FakeActivity(self._dedupe_to, self.calls)


def test_replay_cites_the_deduped_resource_downstream(tmp_path: Path) -> None:
    """The end to end seam: a raw input the deployment already holds comes back under
    a different id, and the output that consumed it has to follow."""
    raw_id, derived_id, existing_id = uuid4(), uuid4(), uuid4()
    bundle = Bundle(tmp_path / "bundle")
    bundle.set_book(
        BundleBook(volume="example", version="v1.0.0", visibility="hidden", license="MIT")
    )
    bundle.set_activity(
        BundleActivity(
            activity_id=uuid4(),
            kind="build",
            code_ref="test",
            config_hash="sha256:" + "0" * 64,
        )
    )
    for tracking_id, used in ((raw_id, []), (derived_id, [BundleUsedRef(tracking_id=raw_id)])):
        data = f"payload {tracking_id}".encode()
        bundle.add_resource(
            data=data,
            hash_=sha256_hex(data),
            type_="tabular",
            tracking_id=tracking_id,
            generated=True,
            used=used,
        )
    bundle.add_book_entry(name_in_book="data", tracking_id=derived_id)
    bundle.mark_book_published()
    bundle.write()

    bs = _FakeBookshelf({raw_id: existing_id})
    replay_bundle_sync(bundle, bs)  # type: ignore[arg-type]

    sent = dict(bs.calls)
    assert sent[raw_id] == []
    assert sent[derived_id] == [existing_id], "the derived output must cite what came back"
    assert bs.draft.published
