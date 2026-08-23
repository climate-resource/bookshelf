"""Offline tests for the 0.4 compatibility shim in ``bookshelf.legacy``."""

import io
import re
import warnings
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

import bookshelf
from bookshelf import legacy
from bookshelf._core import config
from bookshelf.cache import ContentCache, default_cache_dir
from bookshelf.facade import Bookshelf
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"
TRACKING_ID = payloads.RESOURCE_READ["tracking_id"]
BOOK_ID = payloads.BOOK_DETAIL["book_id"]

WIDE = pd.DataFrame(
    {
        "model": ["m"] * 3,
        "region": ["NZL", "NZL", "AUS"],
        "scenario": ["s"] * 3,
        "unit": ["Mt CO2/yr", "Mt CH4/yr", "Mt CO2/yr"],
        "variable": ["Emissions|CO2", "Emissions|CH4", "Emissions|CO2"],
        "2000-01-01": [1.0, 2.0, 3.0],
        "2001-01-01": [1.5, 2.5, 3.5],
    }
)


def _parquet(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    return buffer.getvalue()


def _books(versions: list[tuple[str, int]]) -> dict[str, Any]:
    items = [
        dict(
            payloads.book_list_item(status="published"),
            id=BOOK_ID,
            volume_name="primap-hist",
            version=v,
            edition=e,
        )
        for v, e in versions
    ]
    return dict(payloads.BOOK_LIST, items=items, total=len(items))


def _entries(*names: str) -> dict[str, Any]:
    return {
        "items": [
            dict(payloads.ENTRY_ATTACHED, name_in_book=name, type="timeseries", visibility="public")
            for name in names
        ],
        "next_cursor": None,
    }


def _platform(
    versions: list[tuple[str, int]],
    *,
    entries: tuple[str, ...] = ("by_country",),
    frame: pd.DataFrame = WIDE,
) -> httpx.MockTransport:
    """A volume holding ``versions``, every book sharing one timeseries entry."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/books":
            params = request.url.params
            if params.get("volume") != "primap-hist":
                return httpx.Response(404, json={"detail": "no such volume"})
            wanted = params.get("version")
            chosen = [(v, e) for v, e in versions if wanted is None or v == wanted]
            return httpx.Response(200, json=_books(chosen))
        if re.fullmatch(r"/v1/books/[^/]+/entries", path):
            return httpx.Response(200, json=_entries(*entries))
        if path == f"/v1/resources/{TRACKING_ID}/data":
            return httpx.Response(
                200, content=_parquet(frame), headers={"content-type": "application/parquet"}
            )
        if path == f"/v1/resources/{TRACKING_ID}":
            return httpx.Response(200, json=payloads.RESOURCE_READ)
        return httpx.Response(404, json={"detail": f"unhandled {path}"})

    return httpx.MockTransport(handler)


def _shelf(transport: httpx.MockTransport, tmp_path: Path) -> legacy.BookShelf:
    with pytest.warns(DeprecationWarning, match="bookshelf.BookShelf is deprecated"):
        shelf = legacy.BookShelf()
    shelf._bookshelf = Bookshelf(BASE_URL, auth=None, transport=transport)
    shelf._bookshelf._cache = ContentCache(tmp_path / "cache")
    return shelf


def test_the_package_serves_the_legacy_names_with_a_warning() -> None:
    with pytest.warns(DeprecationWarning, match="bookshelf.BookShelf is deprecated"):
        assert bookshelf.BookShelf is legacy.BookShelf
    with pytest.warns(DeprecationWarning, match="bookshelf.LocalBook is deprecated"):
        assert bookshelf.LocalBook is legacy.LocalBook
    with pytest.raises(AttributeError, match="no attribute 'Nope'"):
        bookshelf.Nope  # noqa: B018


def test_a_remote_bookshelf_url_is_reported_as_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", BASE_URL)
    with (
        pytest.warns(DeprecationWarning),
        pytest.warns(UserWarning, match=r"remote_bookshelf='https://s3.test/v0.3.2' is ignored"),
    ):
        shelf = legacy.BookShelf(tmp_path, remote_bookshelf="https://s3.test/v0.3.2")
    assert shelf.remote_bookshelf == BASE_URL
    assert shelf.path == tmp_path


def test_the_path_becomes_the_content_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", BASE_URL)
    with pytest.warns(DeprecationWarning):
        shelf = legacy.BookShelf(tmp_path / "books")
    assert shelf._bookshelf._cache.base_dir == tmp_path / "books"
    assert (tmp_path / "books").is_dir()


def test_load_defaults_to_the_latest_version_and_edition(tmp_path: Path) -> None:
    shelf = _shelf(_platform([("v2.5", 1), ("v2.6", 1), ("v2.6", 2)]), tmp_path)

    with pytest.warns(DeprecationWarning, match="BookShelf.load"):
        book = shelf.load("primap-hist")

    assert (book.name, book.version, book.edition) == ("primap-hist", "v2.6", 2)
    assert book.long_version() == "v2.6_e002"


def test_load_raises_the_legacy_errors(tmp_path: Path) -> None:
    shelf = _shelf(_platform([("v2.6", 1)]), tmp_path)

    with pytest.warns(DeprecationWarning), pytest.raises(legacy.UnknownBook, match="'nope'"):
        shelf.load("nope")
    with pytest.warns(DeprecationWarning), pytest.raises(legacy.UnknownVersion) as version:
        shelf.load("primap-hist", "v9")
    assert str(version.value) == "Could not find primap-hist@v9"
    with pytest.warns(DeprecationWarning), pytest.raises(legacy.UnknownEdition) as edition:
        shelf.load("primap-hist", "v2.6", 7)
    assert str(edition.value) == "Could not find primap-hist@v2.6 ed.7"
    assert isinstance(edition.value, legacy.UnknownVersion)


def test_list_versions_and_is_available(tmp_path: Path) -> None:
    shelf = _shelf(_platform([("v2.5", 1), ("v2.6", 1), ("v2.6", 2)]), tmp_path)

    with pytest.warns(DeprecationWarning, match="list_versions"):
        assert shelf.list_versions("primap-hist") == ["v2.5", "v2.6"]
    with pytest.warns(DeprecationWarning, match="list_versions"), pytest.raises(legacy.UnknownBook):
        shelf.list_versions("nope")
    with pytest.warns(DeprecationWarning, match="is_available"):
        assert shelf.is_available("primap-hist")
        assert shelf.is_available("primap-hist", "v2.6", 2)
        assert not shelf.is_available("primap-hist", "v2.6", 3)
        assert not shelf.is_available("primap-hist", "v1")
        assert not shelf.is_available("nope")


def test_is_cached_reflects_the_content_cache(tmp_path: Path) -> None:
    shelf = _shelf(_platform([("v2.6", 1)]), tmp_path)

    with pytest.warns(DeprecationWarning, match="is_cached"):
        assert not shelf.is_cached("primap-hist", "v2.6", 1)
        shelf._bookshelf._cache.put(payloads.RESOURCE_READ["hash"], b"")
        assert shelf.is_cached("primap-hist", "v2.6", 1)
        assert not shelf.is_cached("nope", "v2.6", 1)


def test_metadata_is_a_plain_dict_in_the_datapackage_shape(tmp_path: Path) -> None:
    shelf = _shelf(_platform([("v2.6", 5)], entries=("by_country", "by_region")), tmp_path)

    with pytest.warns(DeprecationWarning):
        metadata = shelf.load("primap-hist", "v2.6", 5).metadata()

    assert metadata["name"] == "primap-hist"
    assert metadata["version"] == "v2.6"
    assert metadata["edition"] == 5
    assert metadata["private"] is True
    assert [resource["name"] for resource in metadata["resources"]] == ["by_country", "by_region"]
    assert metadata["resources"][0]["timeseries_name"] == "by_country"
    assert metadata["resources"][0]["type"] == "timeseries"


def test_timeseries_reads_the_whole_wide_resource_as_an_scmrun(tmp_path: Path) -> None:
    pytest.importorskip("scmdata")
    shelf = _shelf(_platform([("v2.6", 5)]), tmp_path)

    with pytest.warns(DeprecationWarning, match="LocalBook.timeseries"):
        run = shelf.load("primap-hist", "v2.6", 5).timeseries("by_country")

    assert run.shape == (3, 2)
    assert sorted(run.meta.columns) == ["model", "region", "scenario", "unit", "variable"]
    assert [t.year for t in run["time"]] == [2000, 2001]
    assert run.filter(region="AUS").values.tolist() == [[3.0, 3.5]]


def test_the_legacy_shape_suffix_is_stripped_from_a_resource_name(tmp_path: Path) -> None:
    pytest.importorskip("scmdata")
    shelf = _shelf(_platform([("v2.6", 5)]), tmp_path)

    with pytest.warns(DeprecationWarning):
        book = shelf.load("primap-hist", "v2.6", 5)
        assert book.timeseries("by_country_wide").shape == (3, 2)
        assert len(book.get_long_format_data("by_country_long")) == 6
        with pytest.raises(ValueError, match="Unknown timeseries 'by_region'"):
            book.timeseries("by_region")


def test_get_long_format_data_matches_the_legacy_writer(tmp_path: Path) -> None:
    """The 0.4 writer sorted by every dimension then year, named the value ``values``,
    and left the year as a date-stamped string."""
    shelf = _shelf(_platform([("v2.6", 5)]), tmp_path)

    with pytest.warns(DeprecationWarning, match="get_long_format_data"):
        long = shelf.load("primap-hist", "v2.6", 5).get_long_format_data("by_country")

    expected = pd.DataFrame(
        {
            "model": ["m"] * 6,
            "region": ["AUS", "AUS", "NZL", "NZL", "NZL", "NZL"],
            "scenario": ["s"] * 6,
            "unit": ["Mt CO2/yr"] * 2 + ["Mt CH4/yr"] * 2 + ["Mt CO2/yr"] * 2,
            "variable": ["Emissions|CO2"] * 2 + ["Emissions|CH4"] * 2 + ["Emissions|CO2"] * 2,
            "year": ["2000-01-01 00:00:00", "2001-01-01 00:00:00"] * 3,
            "values": [3.0, 3.5, 2.0, 2.5, 1.0, 1.5],
        }
    )
    pd.testing.assert_frame_equal(long, expected)


def test_as_long_df_keeps_its_tidy_shape_by_default(tmp_path: Path) -> None:
    client = Bookshelf(BASE_URL, auth=None, transport=_platform([("v2.6", 5)]))
    long = client.resource(TRACKING_ID).as_long_df()
    assert list(long.columns) == [
        "model",
        "region",
        "scenario",
        "unit",
        "variable",
        "year",
        "value",
    ]
    assert long["year"].tolist() == [2000, 2000, 2000, 2001, 2001, 2001]


def test_the_legacy_cache_location_variable_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOKSHELF_CACHE_DIR", raising=False)
    monkeypatch.setenv("BOOKSHELF_CACHE_LOCATION", "/legacy/cache")
    assert default_cache_dir() == Path("/legacy/cache")
    monkeypatch.setenv("BOOKSHELF_CACHE_DIR", "/new/cache")
    assert default_cache_dir() == Path("/new/cache")


def test_a_legacy_remote_variable_warns_rather_than_vanishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKSHELF_REMOTE", "https://s3.test/v0.3.2")
    with pytest.warns(UserWarning, match="BOOKSHELF_REMOTE is ignored"):
        assert config.resolve_base_url(BASE_URL) == BASE_URL
    monkeypatch.delenv("BOOKSHELF_REMOTE")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert config.resolve_base_url(BASE_URL) == BASE_URL
