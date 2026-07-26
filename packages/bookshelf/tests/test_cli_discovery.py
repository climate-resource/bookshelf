"""CLI tests for ``bookshelf search`` and ``bookshelf show`` against the live app."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf_api.models.book import Book, BookStatus
from bookshelf_api.models.enums import Visibility
from bookshelf_api.models.resource import Resource, ResourceType
from bookshelf_api.models.volume import Volume

runner = CliRunner()

_PUBLISHED = datetime(2026, 5, 14, 9, 22, 41, tzinfo=UTC)


@pytest.fixture
async def catalogue(db_session: AsyncSession) -> dict[str, str]:
    """Two public volumes, one with published books and files at every depth."""
    primap = Volume(
        name="primap-hist",
        description="PRIMAP-hist national emissions",
        license="CC-BY-4.0",
        owner_org_id="org_cli_1",
        metadata_={},
        discovery={
            "title": "PRIMAP-hist national emissions",
            "publisher": "PIK",
            "topics": ["emissions"],
            "spatial_coverage": ["GLB", "AUS"],
        },
    )
    ngfs = Volume(
        name="ngfs-emissions",
        description="NGFS scenario emissions",
        license="CC-BY-4.0",
        owner_org_id="org_cli_1",
        metadata_={},
        discovery={"title": "NGFS scenario emissions", "topics": ["scenarios"]},
    )
    db_session.add_all([primap, ngfs])
    await db_session.flush()

    def book(
        volume: Volume,
        edition: int,
        *,
        version: str = "1.0.0",
        status: BookStatus = BookStatus.PUBLISHED,
    ) -> Book:
        published = status is BookStatus.PUBLISHED
        return Book(
            volume_id=volume.id,
            version=version,
            edition=edition,
            status=status,
            visibility=Visibility.PUBLIC,
            metadata_={},
            data_dictionary=[],
            hash=("e" * 64) if published else None,
            published_at=_PUBLISHED if published else None,
        )

    e1 = book(primap, 1)
    e2 = book(primap, 2)
    e3 = book(primap, 3, status=BookStatus.DRAFT)
    prerelease = book(primap, 1, version="1.0.0-beta")
    ngfs_book = book(ngfs, 1)
    db_session.add_all([e1, e2, e3, prerelease, ngfs_book])
    await db_session.flush()
    db_session.add(
        Resource(
            book_id=e2.id,
            name="by_country",
            type=ResourceType.TIMESERIES,
            format="parquet",
            size_bytes=4404019,
            hash="sha256:" + "9" * 64,
            content_hash="9f1c" + "0" * 60,
            storage_path="s3://bucket/key",
            visibility=Visibility.PUBLIC,
            owner_org_id="org_cli_1",
            metadata_={},
        )
    )
    await db_session.commit()
    return {"primap": primap.name, "ngfs": ngfs.name}


async def test_search_lists_and_filters_volumes(cli_env: str, catalogue: dict[str, str]) -> None:
    result = runner.invoke(app, ["search"])
    assert result.exit_code == 0, result.stderr
    assert "primap-hist" in result.stdout
    assert "ngfs-emissions" in result.stdout

    result = runner.invoke(app, ["search", "PRIMAP"])
    assert result.exit_code == 0
    assert "primap-hist" in result.stdout
    assert "ngfs-emissions" not in result.stdout


async def test_search_json_emits_one_object_per_result(
    cli_env: str, catalogue: dict[str, str]
) -> None:
    result = runner.invoke(app, ["search", "--json", "--limit", "1"])
    assert result.exit_code == 0
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {
        "name",
        "title",
        "latest_version",
        "latest_edition",
        "resource_types",
        "topics",
        "license",
    }


async def test_search_topic_filter_narrows(cli_env: str, catalogue: dict[str, str]) -> None:
    result = runner.invoke(app, ["search", "--topic", "emissions", "--json"])
    assert result.exit_code == 0
    names = [json.loads(line)["name"] for line in result.stdout.splitlines()]
    assert names == ["primap-hist"]


async def test_search_facets_lists_filter_values(cli_env: str, catalogue: dict[str, str]) -> None:
    result = runner.invoke(app, ["search", "--facets", "--json"])
    assert result.exit_code == 0, result.stderr
    facets = json.loads(result.stdout)
    assert "emissions" in facets["topics"]
    assert set(facets) >= {"topics", "regions", "publishers", "licences", "types"}


async def test_show_volume_lists_versions_and_editions(
    cli_env: str, catalogue: dict[str, str]
) -> None:
    result = runner.invoke(app, ["show", "primap-hist", "--json"])
    assert result.exit_code == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["name"] == "primap-hist"
    assert document["publisher"] == "PIK"
    versions = {v["version"]: v["editions"] for v in document["versions"]}
    assert sorted(e["edition"] for e in versions["1.0.0"]) == [1, 2, 3]


async def test_show_book_resolves_the_latest_published_edition(
    cli_env: str, catalogue: dict[str, str]
) -> None:
    """The draft e003 must not win: omitting the edition means latest published."""
    result = runner.invoke(app, ["show", "primap-hist@1.0.0", "--json"])
    assert result.exit_code == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["address"] == "primap-hist@1.0.0_e002"
    assert document["status"] == "published"
    assert [r["name"] for r in document["resources"]] == ["by_country"]


async def test_show_file_resolves_mixed_version_shapes(
    cli_env: str, catalogue: dict[str, str]
) -> None:
    result = runner.invoke(app, ["show", "primap-hist/by_country", "--json"])
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["book"] == "primap-hist@1.0.0_e002"


async def test_show_book_resolves_an_exact_edition(cli_env: str, catalogue: dict[str, str]) -> None:
    result = runner.invoke(app, ["show", "primap-hist@1.0.0_e001", "--json"])
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["address"] == "primap-hist@1.0.0_e001"


async def test_show_file_reports_format_size_and_hash(
    cli_env: str, catalogue: dict[str, str]
) -> None:
    result = runner.invoke(app, ["show", "primap-hist@1.0.0_e002/by_country", "--json"])
    assert result.exit_code == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["name"] == "by_country"
    assert document["format"] == "parquet"
    assert document["bytes"] == 4404019
    assert document["content_hash"].startswith("9f1c")
    assert document["book"] == "primap-hist@1.0.0_e002"


async def test_show_unknown_volume_exits_5(cli_env: str, catalogue: dict[str, str]) -> None:
    result = runner.invoke(app, ["show", "no-such-volume"])
    assert result.exit_code == 5
    assert result.stdout == ""


async def test_show_unknown_edition_exits_5_and_names_the_fix(
    cli_env: str, catalogue: dict[str, str]
) -> None:
    result = runner.invoke(app, ["show", "primap-hist@1.0.0_e009"])
    assert result.exit_code == 5
    assert "bookshelf show primap-hist" in result.stderr


async def test_show_unknown_file_exits_5(cli_env: str, catalogue: dict[str, str]) -> None:
    result = runner.invoke(app, ["show", "primap-hist@1.0.0_e002/nope"])
    assert result.exit_code == 5


async def test_malformed_address_is_a_usage_error_and_never_reaches_the_api(
    catalogue: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", "http://127.0.0.1:9")
    result = runner.invoke(app, ["show", "bad address"])
    assert result.exit_code == 2
    assert "malformed address" in result.stderr


async def test_network_failure_exits_6(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", "http://127.0.0.1:9")
    result = runner.invoke(app, ["search"])
    assert result.exit_code == 6
