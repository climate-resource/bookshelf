"""The 0.4 names and settings that are gone or on their way out, and what each one says."""

import importlib
import sys
import warnings
from pathlib import Path

import pandas as pd
import pytest

import bookshelf
from bookshelf._core import config
from bookshelf._facade import Bookshelf
from bookshelf.cache import default_cache_dir
from tests._platform import BASE_URL, TRACKING_ID, _platform


@pytest.mark.parametrize("name", ["BookShelf", "LocalBook"])
def test_a_removed_0_4_name_points_at_the_migration_guide(name: str) -> None:
    with pytest.raises(
        AttributeError, match=rf"bookshelf.{name} was removed in bookshelf 1.1.*migrating/"
    ):
        getattr(bookshelf, name)
    with pytest.raises(AttributeError, match="no attribute 'Nope'"):
        bookshelf.Nope  # noqa: B018


def test_as_long_df_keeps_its_tidy_shape_by_default() -> None:
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


def test_legacy_columns_matches_the_0_4_writer() -> None:
    """The 0.4 writer sorted by every dimension then year.

    It named the value ``values`` and left the year as a date-stamped string.
    """
    client = Bookshelf(BASE_URL, auth=None, transport=_platform([("v2.6", 5)]))

    with pytest.warns(DeprecationWarning, match="legacy_columns"):
        long = client.resource(TRACKING_ID).as_long_df(legacy_columns=True)

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


def test_the_legacy_cache_location_variable_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOKSHELF_CACHE_DIR", raising=False)
    monkeypatch.setenv("BOOKSHELF_CACHE_LOCATION", "/legacy/cache")
    with pytest.warns(FutureWarning, match="set BOOKSHELF_CACHE_DIR instead"):
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


@pytest.mark.parametrize(
    "module",
    ["shelf", "book", "errors", "utils", "schema", "constants", "dataset_structure", "legacy"],
)
def test_a_removed_0_4_submodule_points_at_the_migration_guide(module: str) -> None:
    sys.modules.pop(f"bookshelf.{module}", None)
    with pytest.raises(ImportError, match=r"migrating/") as caught:
        importlib.import_module(f"bookshelf.{module}")

    assert not isinstance(caught.value, ModuleNotFoundError)
    assert f"bookshelf.{module} was removed" in str(caught.value)
