"""A Volume answers what a dataset has published, which the catalogue could not say before.

Finding the versions of a volume used to mean calling ``list_books`` and reading
``version`` off each generated model.
The handle asks the platform once and indexes the answer.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from bookshelf._consume.volumes import AsyncVolume, Volume
from bookshelf._core.errors import NotFoundError
from bookshelf._generated import models
from bookshelf.cache import ContentCache

NOW = datetime(2026, 1, 1, tzinfo=UTC)
BOOK_ID = "0193f0f3-0000-7000-8000-000000000001"


def _edition(number: int, status: str = "published") -> models.EditionInfo:
    return models.EditionInfo(edition=number, status=status, created_at=NOW, published_at=NOW)


def _detail(*versions: models.VersionInfo, description: str | None = None) -> Any:
    return models.VolumeDetailResponse(
        id="01",
        name="primap-hist",
        owner_org_id="org",
        metadata={},
        discovery=models.DiscoveryProfile(license="CC-BY-4.0", description=description),
        created_at=NOW,
        updated_at=NOW,
        versions=list(versions),
        stats=models.VolumeStats(
            total_versions=len(versions),
            total_editions=sum(len(info.editions) for info in versions),
            total_resources=12,
            total_size_bytes=48_300_000,
        ),
    )


class _FakeClient:
    """Answers the one book lookup a version resolution makes."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    def list_books(self, *, volume: str, version: str, **kwargs: Any) -> Any:
        self.asked.append((volume, version))
        return models.BookListResponse(
            items=[
                models.BookListItem(
                    id=BOOK_ID,
                    volume_name=volume,
                    version=version,
                    edition=5,
                    status=models.BookStatus.published,
                    visibility=models.Visibility.public,
                    metadata={},
                    created_at=NOW,
                    published_at=NOW,
                )
            ],
            total=1,
            limit=100,
            offset=0,
            has_more=False,
        )

    def list_book_entries(self, book_id: str, **kwargs: Any) -> Any:
        return models.BookEntriesResponse(items=[], next_cursor=None)


@pytest.fixture
def cache(tmp_path: Path) -> ContentCache:
    return ContentCache(base_dir=tmp_path)


@pytest.fixture
def volume(cache: ContentCache) -> Volume:
    """A volume whose versions arrive out of order, as the API is free to send them."""
    return Volume(
        _FakeClient(),  # type: ignore[arg-type]
        cache,
        _detail(
            models.VersionInfo(version="v2.6", editions=[_edition(n) for n in (1, 2, 3, 4, 5)]),
            models.VersionInfo(version="v2.4", editions=[_edition(1), _edition(2)]),
            models.VersionInfo(version="v2.5", editions=[_edition(1)]),
        ),
    )


def test_a_volume_orders_its_versions_rather_than_trusting_the_api(volume: Volume) -> None:
    """The API sends versions in no promised order, and a reader wants the newest last."""
    assert volume.versions == ("v2.4", "v2.5", "v2.6")
    assert volume.latest == "v2.6"
    assert list(volume) == ["v2.4", "v2.5", "v2.6"]
    assert "v2.5" in volume
    assert len(volume) == 3


def test_editions_reports_only_the_published_ones(cache: ContentCache) -> None:
    """A draft edition exists on the platform but is not something a consumer can read."""
    volume = Volume(
        _FakeClient(),  # type: ignore[arg-type]
        cache,
        _detail(
            models.VersionInfo(
                version="v2.6",
                editions=[_edition(1), _edition(2, status="draft"), _edition(3)],
            )
        ),
    )

    assert volume.editions("v2.6") == (1, 3)


def test_an_unknown_version_says_which_ones_exist(volume: Volume) -> None:
    """The whole point of the handle is to answer this without a second round trip."""
    with pytest.raises(NotFoundError, match="v2.4, v2.5, v2.6"):
        volume.editions("v9.9")


def test_printing_a_volume_names_its_versions_and_their_edition_ranges(volume: Volume) -> None:
    printed = repr(volume)

    assert "Bookshelf Volume 'primap-hist' (versions: 3)" in printed
    assert "latest     v2.6_e005" in printed
    assert "v2.4  editions 001-002" in printed
    assert "v2.5  edition 001" in printed
    assert 'volume["v2.6"]' in printed


def test_a_volume_repr_unwraps_the_discovery_root_models(cache: ContentCache) -> None:
    """Discovery fields are RootModels, and printing one raw shows ``root='...'``."""
    volume = Volume(
        _FakeClient(),  # type: ignore[arg-type]
        cache,
        _detail(
            models.VersionInfo(version="v2.6", editions=[_edition(1)]),
            description="National greenhouse gas emissions.",
        ),
    )

    printed = repr(volume)

    assert "license      CC-BY-4.0" in printed
    assert "description  National greenhouse gas emissions." in printed
    assert "root=" not in printed


def test_asking_for_a_book_without_a_version_resolves_the_latest(volume: Volume) -> None:
    """The common case, which otherwise means listing books and sorting them yourself."""
    book = volume.book()

    assert book.metadata.version == "v2.6"
    assert volume._client.asked == [("primap-hist", "v2.6")]  # type: ignore[attr-defined]


def test_indexing_a_volume_resolves_that_version(volume: Volume) -> None:
    assert volume["v2.4"].metadata.version == "v2.4"


def test_a_volume_with_nothing_published_refuses_to_guess_a_latest(cache: ContentCache) -> None:
    """An empty volume has no newest book, and saying so beats a confusing lookup failure."""
    empty = Volume(_FakeClient(), cache, _detail())  # type: ignore[arg-type]

    assert empty.latest is None
    assert 'volume["<version>"]' in repr(empty)
    with pytest.raises(NotFoundError, match="published no book"):
        empty.book()


def test_a_version_with_only_drafts_is_not_a_version_you_can_read(cache: ContentCache) -> None:
    """A draft-only version becoming `latest` would make `volume.book()` raise."""
    volume = Volume(
        _FakeClient(),  # type: ignore[arg-type]
        cache,
        _detail(
            models.VersionInfo(version="v2.6", editions=[_edition(1)]),
            models.VersionInfo(version="v2.7", editions=[_edition(1, status="draft")]),
        ),
    )

    assert volume.versions == ("v2.6",)
    assert volume.latest == "v2.6"


def test_the_async_twin_advertises_a_call_it_actually_has(cache: ContentCache) -> None:
    """An index cannot be awaited, so `volume["v2.6"]` would raise on the async flavour."""
    detail = _detail(models.VersionInfo(version="v2.6", editions=[_edition(1)]))
    sync_hint = repr(Volume(_FakeClient(), cache, detail))  # type: ignore[arg-type]
    async_hint = repr(AsyncVolume(_FakeClient(), cache, detail))  # type: ignore[arg-type]

    assert 'volume["v2.6"]' in sync_hint
    assert 'await volume.book("v2.6")' in async_hint
    assert not hasattr(AsyncVolume, "__getitem__")
