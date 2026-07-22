import io
import json
import pathlib
import platform
import re

import platformdirs
import pytest
import requests

from bookshelf.backends.api import APIBackend
from bookshelf.backends.s3 import S3Backend
from bookshelf.constants import DATA_FORMAT_VERSION
from bookshelf.errors import OfflineError, UnknownBook, UnknownVersion
from bookshelf.shelf import BookShelf, LocalBook


@pytest.fixture()
def shelf(local_bookshelf):
    shelf = BookShelf(path=local_bookshelf)
    return shelf


def get_meta(conn, bucket, pkg):
    volume_meta_contents = io.BytesIO()
    conn.Object(bucket, f"/this/prefix/{pkg}/volume.json").download_fileobj(volume_meta_contents)
    volume_meta_contents.seek(0)
    return json.load(volume_meta_contents)


def test_local_cache(monkeypatch):
    # Override the local_bookshelf fixture
    monkeypatch.delenv("BOOKSHELF_CACHE_LOCATION")

    shelf = BookShelf()

    if platform.system() == "Windows":
        exp = pathlib.Path(platformdirs.user_cache_dir()) / "bookshelf" / "Cache" / DATA_FORMAT_VERSION
    else:
        exp = pathlib.Path(platformdirs.user_cache_dir()) / "bookshelf" / DATA_FORMAT_VERSION
    assert shelf.path == exp


def test_load_missing(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/missing/volume.json", status_code=404)

    with pytest.raises(UnknownBook, match=re.escape("No metadata for 'missing'")):
        shelf.load("missing")


def test_load_missing_version(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/test/v1.1.1/datapackage.json", status_code=404)
    with pytest.raises(UnknownVersion, match=re.escape("Could not find test@v1.1.1")):
        shelf.load("test", "v1.1.1")

    with pytest.raises(UnknownVersion, match=re.escape("Could not find test@v1.1.1")):
        shelf.load("test", "v1.1.1", force=True)


def test_load(remote_bookshelf, shelf):
    book = shelf.load("test")
    assert book.version == "v1.1.0"

    book = shelf.load("test", "v1.1.0")
    assert book.version == "v1.1.0"

    book = shelf.load("test", "v1.0.0")
    assert book.version == "v1.0.0"


def test_load_with_cached(remote_bookshelf, local_bookshelf):
    shelf = BookShelf(path=local_bookshelf)
    shelf.load("test")

    remote_bookshelf.mocker.reset()
    remote_bookshelf.register("test", "v1.1.0", 2)
    remote_bookshelf.register("test", "v1.2.1", 1)

    shelf = BookShelf(path=local_bookshelf)
    shelf.load("test", "v1.1.0", 1)
    assert remote_bookshelf.mocker.call_count == 0

    # Not providing an edition causes a fetch of the volume and datapackage
    book = shelf.load("test", "v1.1.0")
    assert book.edition == 2
    assert remote_bookshelf.mocker.call_count == 2

    # A cache miss causes a fetch of the data package
    shelf.load("test", "v1.2.1", 1)
    assert remote_bookshelf.mocker.call_count == 3

    # Not providing a version/edition always causes a fetch
    shelf.load("test")
    assert remote_bookshelf.mocker.call_count == 4


def test_is_available(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/other/volume.json", status_code=404)

    assert shelf.is_available("test", "v1.0.0")
    assert shelf.is_available("test", "v1.1.0")

    assert not shelf.is_available("test", "v1.1.1")
    assert not shelf.is_available("other", "v1.1.0")


def test_is_available_any_version(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/other/volume.json", status_code=404)

    assert shelf.is_available("test")
    assert not shelf.is_available("other")


def test_is_cached(shelf):
    book = LocalBook.create_new("test", "v1.0.0", edition=1, local_bookshelf=shelf.path)

    assert shelf.is_cached(book.name, book.version, edition=1)
    assert not shelf.is_cached(book.name, "v1.0.1", 1)
    assert not shelf.is_cached("other", "v1.0.1", 1)


def test_list_versions(shelf, remote_bookshelf):
    remote_bookshelf.mocker.get(f"/{DATA_FORMAT_VERSION}/other/volume.json", status_code=404)

    assert shelf.list_versions("test") == ["v1.0.0", "v1.1.0"]
    with pytest.raises(UnknownBook):
        shelf.list_versions("other")


@pytest.mark.xfail(reason="Not implemented")
def test_list_name(shelf):
    assert shelf.list_books() == ["test"]


def test_private_list(remote_bookshelf, local_bookshelf):
    remote_bookshelf.register("test", "v2_private", 1, private=True)
    shelf = BookShelf(path=local_bookshelf)

    assert shelf.list_versions("test") == ["v1.0.0", "v1.1.0"]
    assert shelf.load("test", "v2_private")

    assert shelf.load("test").version == "v1.1.0"


# ===== Backend env var selection tests =====


def test_backend_env_var_defaults_to_s3(shelf):
    """Default backend is S3Backend when BOOKSHELF_BACKEND is not set."""
    assert isinstance(shelf._backend, S3Backend)


def test_backend_env_var_selects_api(monkeypatch, local_bookshelf):
    """BOOKSHELF_BACKEND=api selects APIBackend."""
    monkeypatch.setenv("BOOKSHELF_BACKEND", "api")
    monkeypatch.setenv("BOOKSHELF_API_URL", "https://api.example.com")
    monkeypatch.setenv("BOOKSHELF_TOKEN", "test-token")

    shelf = BookShelf(path=local_bookshelf)
    assert isinstance(shelf._backend, APIBackend)


def test_backend_env_var_case_insensitive(monkeypatch, local_bookshelf):
    """BOOKSHELF_BACKEND is case-insensitive."""
    monkeypatch.setenv("BOOKSHELF_BACKEND", "API")
    monkeypatch.setenv("BOOKSHELF_API_URL", "https://api.example.com")
    monkeypatch.setenv("BOOKSHELF_TOKEN", "test-token")

    shelf = BookShelf(path=local_bookshelf)
    assert isinstance(shelf._backend, APIBackend)


def test_explicit_backend_overrides_env_var(monkeypatch, local_bookshelf):
    """Explicit backend parameter takes precedence over env var."""
    monkeypatch.setenv("BOOKSHELF_BACKEND", "api")
    monkeypatch.setenv("BOOKSHELF_API_URL", "https://api.example.com")
    monkeypatch.setenv("BOOKSHELF_TOKEN", "test-token")

    s3 = S3Backend(remote_bookshelf="https://example.com", local_cache=local_bookshelf)
    shelf = BookShelf(path=local_bookshelf, backend=s3)
    assert isinstance(shelf._backend, S3Backend)


# ===== Offline fallback tests =====


def test_offline_fallback_with_cached_version_and_edition(remote_bookshelf, local_bookshelf):
    """When network is down with cached data and explicit version+edition, return cached book."""
    shelf = BookShelf(path=local_bookshelf)

    # First load to populate cache
    book = shelf.load("test", "v1.0.0")
    assert book.version == "v1.0.0"

    # Now make network fail
    prefix = f"https://bookshelf.local/{DATA_FORMAT_VERSION}"
    remote_bookshelf.mocker.get(
        f"{prefix}/test/volume.json",
        exc=requests.exceptions.ConnectionError("Network down"),
    )

    # With explicit version+edition, edition=None triggers resolve_version
    # so we need to also cache with explicit edition
    shelf2 = BookShelf(path=local_bookshelf)
    book = shelf2.load("test", "v1.0.0", edition=1)
    assert book.version == "v1.0.0"
    assert book.edition == 1


def test_offline_fallback_no_version_uses_latest_cached(remote_bookshelf, local_bookshelf):
    """When network is down with no version specified, fall back to latest cached version."""
    shelf = BookShelf(path=local_bookshelf)

    # Populate cache with two versions
    shelf.load("test", "v1.0.0")
    shelf.load("test", "v1.1.0")

    # Now make network fail
    prefix = f"https://bookshelf.local/{DATA_FORMAT_VERSION}"
    remote_bookshelf.mocker.get(
        f"{prefix}/test/volume.json",
        exc=requests.exceptions.ConnectionError("Network down"),
    )

    shelf2 = BookShelf(path=local_bookshelf)
    book = shelf2.load("test")
    # Should fall back to latest cached version (v1.1.0)
    assert book.version == "v1.1.0"


def test_offline_fallback_no_cache_raises_offline_error(remote_bookshelf, local_bookshelf):
    """When network is down with no cached data, raise OfflineError."""
    prefix = f"https://bookshelf.local/{DATA_FORMAT_VERSION}"
    remote_bookshelf.mocker.get(
        f"{prefix}/nocache/volume.json",
        exc=requests.exceptions.ConnectionError("Network down"),
    )

    shelf = BookShelf(path=local_bookshelf)
    with pytest.raises(OfflineError, match=re.escape("Cannot fetch 'nocache'")):
        shelf.load("nocache")


def test_offline_fallback_no_cache_with_version_raises_offline_error(remote_bookshelf, local_bookshelf):
    """When network is down with explicit version but no cache, raise OfflineError."""
    prefix = f"https://bookshelf.local/{DATA_FORMAT_VERSION}"
    remote_bookshelf.mocker.get(
        f"{prefix}/nocache/volume.json",
        exc=requests.exceptions.ConnectionError("Network down"),
    )

    shelf = BookShelf(path=local_bookshelf)
    with pytest.raises(OfflineError, match=re.escape("Cannot fetch 'nocache' version v1.0.0")):
        shelf.load("nocache", "v1.0.0")


def test_offline_fallback_force_does_not_catch(remote_bookshelf, local_bookshelf):
    """force=True should not trigger offline fallback — let the error propagate."""
    shelf = BookShelf(path=local_bookshelf)

    # Populate cache first
    shelf.load("test", "v1.0.0")

    # Now make network fail
    prefix = f"https://bookshelf.local/{DATA_FORMAT_VERSION}"
    remote_bookshelf.mocker.get(
        f"{prefix}/test/volume.json",
        exc=requests.exceptions.ConnectionError("Network down"),
    )

    shelf2 = BookShelf(path=local_bookshelf)
    with pytest.raises(requests.exceptions.ConnectionError):
        shelf2.load("test", force=True)


def test_offline_fallback_http_error_not_caught(remote_bookshelf, local_bookshelf):
    """HTTPError (4xx/5xx) should NOT trigger offline fallback."""
    shelf = BookShelf(path=local_bookshelf)

    # Populate cache
    shelf.load("test", "v1.0.0")

    # Return a 500 error — this should propagate, not trigger fallback
    prefix = f"https://bookshelf.local/{DATA_FORMAT_VERSION}"
    remote_bookshelf.mocker.get(
        f"{prefix}/test/volume.json",
        status_code=500,
    )

    shelf2 = BookShelf(path=local_bookshelf)
    # 500 is not ConnectionError/OSError, so it should raise normally
    # (S3Backend converts all HTTPError to UnknownBook)
    with pytest.raises(UnknownBook):
        shelf2.load("test")


def test_find_cached_versions(local_bookshelf):
    """_find_cached_versions returns sorted (version, edition) tuples."""
    shelf = BookShelf(path=local_bookshelf)

    # Create some cached books
    LocalBook.create_new("mybook", "v1.0.0", edition=1, local_bookshelf=local_bookshelf)
    LocalBook.create_new("mybook", "v1.0.0", edition=2, local_bookshelf=local_bookshelf)
    LocalBook.create_new("mybook", "v2.0.0", edition=1, local_bookshelf=local_bookshelf)

    cached = shelf._find_cached_versions("mybook")
    assert cached == [("v1.0.0", 1), ("v1.0.0", 2), ("v2.0.0", 1)]


def test_find_cached_versions_empty(local_bookshelf):
    """_find_cached_versions returns empty list for unknown volume."""
    shelf = BookShelf(path=local_bookshelf)
    assert shelf._find_cached_versions("nonexistent") == []
