"""Unit tests for backend abstraction layer."""

# ruff: noqa: S106 - Test tokens are intentionally hardcoded

import copy
import json

import httpx
import pytest
import respx

from bookshelf.api.client import BookshelfAPIClient
from bookshelf.backends.api import APIBackend
from bookshelf.backends.s3 import S3Backend
from bookshelf.constants import DATA_FORMAT_VERSION
from bookshelf.errors import UnknownBook, UnknownEdition, UnknownVersion

TEST_BASE_URL = "https://test.example.com"


# ===== S3Backend Tests =====


class TestS3Backend:
    """Tests for S3Backend implementation."""

    @pytest.fixture
    def s3_backend(self, tmp_path, requests_mock):
        """Create an S3Backend with mocked requests."""
        prefix = f"https://bookshelf.local/{DATA_FORMAT_VERSION}"
        backend = S3Backend(remote_bookshelf=prefix, local_cache=tmp_path)

        # Setup mock volume.json
        requests_mock.get(
            f"{prefix}/test/volume.json",
            json={
                "name": "test",
                "license": "MIT",
                "versions": [
                    {
                        "version": "v1.0.0",
                        "edition": 1,
                        "hash": "abc123",
                        "url": f"{prefix}/test/v1.0.0_e001",
                        "private": False,
                    },
                    {
                        "version": "v1.0.0",
                        "edition": 2,
                        "hash": "def456",
                        "url": f"{prefix}/test/v1.0.0_e002",
                        "private": False,
                    },
                    {
                        "version": "v1.1.0",
                        "edition": 1,
                        "hash": "ghi789",
                        "url": f"{prefix}/test/v1.1.0_e001",
                        "private": False,
                    },
                    {
                        "version": "v2.0.0",
                        "edition": 1,
                        "hash": "jkl012",
                        "url": f"{prefix}/test/v2.0.0_e001",
                        "private": True,
                    },
                ],
            },
        )

        # Setup mock datapackage.json
        requests_mock.get(
            f"{prefix}/test/v1.0.0_e001/datapackage.json",
            json={
                "name": "test",
                "version": "v1.0.0",
                "edition": 1,
                "description": "Test book",
                "private": False,
                "resources": [{"name": "data", "format": "csv", "filename": "test.csv"}],
            },
        )

        # Setup mock resource file
        requests_mock.get(
            f"{prefix}/test/v1.0.0_e001/test.csv",
            text="column1,column2\n1,2\n3,4",
        )

        # Setup 404s for missing resources
        requests_mock.get(f"{prefix}/missing/volume.json", status_code=404)
        requests_mock.get(f"{prefix}/test/v9.9.9_e001/datapackage.json", status_code=404)

        return backend

    def test_resolve_version_explicit(self, s3_backend, tmp_path):
        """Test resolve_version with explicit version and edition."""
        # Create necessary directory structure
        (tmp_path / "test").mkdir(exist_ok=True)

        version, edition = s3_backend.resolve_version("test", "v1.0.0", 1)
        assert version == "v1.0.0"
        assert edition == 1

    def test_resolve_version_latest_version(self, s3_backend, tmp_path):
        """Test resolve_version with version=None resolves to latest non-private."""
        # Create necessary directory structure
        (tmp_path / "test").mkdir(exist_ok=True)

        version, edition = s3_backend.resolve_version("test", version=None, edition=1)
        # v2.0.0 is private, so should resolve to v1.1.0
        assert version == "v1.1.0"
        assert edition == 1

    def test_resolve_version_latest_edition(self, s3_backend, tmp_path):
        """Test resolve_version with edition=None resolves to latest edition."""
        # Create necessary directory structure
        (tmp_path / "test").mkdir(exist_ok=True)

        version, edition = s3_backend.resolve_version("test", "v1.0.0", edition=None)
        assert version == "v1.0.0"
        assert edition == 2  # Latest edition for v1.0.0

    def test_resolve_version_unknown_book(self, s3_backend):
        """Test resolve_version raises UnknownBook for missing volume."""
        with pytest.raises(UnknownBook, match="No metadata for 'missing'"):
            s3_backend.resolve_version("missing", "v1.0.0", 1)

    def test_resolve_version_unknown_version(self, s3_backend, tmp_path):
        """Test resolve_version raises UnknownVersion for missing version."""
        # Create necessary directory structure
        (tmp_path / "test").mkdir(exist_ok=True)

        with pytest.raises(UnknownVersion):
            s3_backend.resolve_version("test", "v9.9.9", 1)

    def test_resolve_version_unknown_edition(self, s3_backend, tmp_path):
        """Test resolve_version raises UnknownEdition for missing edition."""
        # Create necessary directory structure
        (tmp_path / "test").mkdir(exist_ok=True)

        with pytest.raises(UnknownEdition):
            s3_backend.resolve_version("test", "v1.0.0", 999)

    def test_list_versions(self, s3_backend, tmp_path):
        """Test list_versions returns non-private versions."""
        # Create necessary directory structure
        (tmp_path / "test").mkdir(exist_ok=True)

        versions = s3_backend.list_versions("test")
        # Note: S3 volume.json has separate entries per edition, so v1.0.0
        # appears twice (ed 1 + ed 2). list_versions does not deduplicate.
        assert versions == ["v1.0.0", "v1.0.0", "v1.1.0"]
        # v2.0.0 is private and should be excluded
        assert "v2.0.0" not in versions

    def test_list_versions_unknown_book(self, s3_backend):
        """Test list_versions raises UnknownBook for missing volume."""
        with pytest.raises(UnknownBook, match="No metadata for 'missing'"):
            s3_backend.list_versions("missing")

    def test_fetch_datapackage(self, s3_backend, tmp_path):
        """Test fetch_datapackage downloads and returns path."""
        local_path = tmp_path / "datapackage.json"
        result_path = s3_backend.fetch_datapackage("test", "v1.0.0", 1, local_path)

        assert result_path == local_path
        assert local_path.exists()

        with open(local_path) as f:
            data = json.load(f)
            assert data["name"] == "test"
            assert data["version"] == "v1.0.0"
            assert data["edition"] == 1

    def test_fetch_datapackage_unknown_version(self, s3_backend, tmp_path):
        """Test fetch_datapackage raises UnknownVersion for 404."""
        local_path = tmp_path / "datapackage.json"

        with pytest.raises(UnknownVersion):
            s3_backend.fetch_datapackage("test", "v9.9.9", 1, local_path)

    def test_download_resource(self, s3_backend, tmp_path):
        """Test download_resource downloads file."""
        local_path = tmp_path / "test.csv"
        s3_backend.download_resource("test", "v1.0.0", 1, "test.csv", local_path)

        assert local_path.exists()
        content = local_path.read_text()
        assert "column1,column2" in content

    def test_list_volumes_not_implemented(self, s3_backend):
        """Test list_volumes raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            s3_backend.list_volumes()


# ===== APIBackend Tests =====


class TestAPIBackend:
    """Tests for APIBackend implementation."""

    @pytest.fixture
    def api_client(self):
        """Create an API client for testing."""
        return BookshelfAPIClient(base_url=TEST_BASE_URL, token="test_token")

    @pytest.fixture
    def api_backend(self, api_client, tmp_path):
        """Create an APIBackend for testing."""
        return APIBackend(client=api_client, local_cache=tmp_path)

    @pytest.fixture
    def mock_volume_detail(self):
        """Sample volume detail response with multiple versions."""
        return {
            "id": "vol_1",
            "name": "test",
            "description": "Test volume",
            "license": "MIT",
            "metadata": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "versions": [
                {
                    "version": "v1.0.0",
                    "editions": [
                        {
                            "edition": 1,
                            "status": "published",
                            "created_at": "2024-01-01T00:00:00Z",
                            "published_at": "2024-01-01T00:00:00Z",
                        },
                        {
                            "edition": 2,
                            "status": "published",
                            "created_at": "2024-01-02T00:00:00Z",
                            "published_at": "2024-01-02T00:00:00Z",
                        },
                    ],
                },
                {
                    "version": "v1.1.0",
                    "editions": [
                        {
                            "edition": 1,
                            "status": "published",
                            "created_at": "2024-01-03T00:00:00Z",
                            "published_at": "2024-01-03T00:00:00Z",
                        }
                    ],
                },
            ],
            "stats": {
                "total_versions": 2,
                "total_editions": 3,
                "total_resources": 5,
                "total_size_bytes": 1024000,
            },
        }

    @pytest.fixture
    def mock_book_response(self):
        """Sample book response."""
        return {
            "id": "book_1",
            "volume_id": "vol_1",
            "version": "v1.0.0",
            "edition": 1,
            "description": "Test book",
            "status": "published",
            "private": False,
            "metadata": {},
            "data_dictionary": [],
            "hash": "abc123",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "published_at": "2024-01-01T00:00:00Z",
            "resources": [
                {
                    "id": "res_1",
                    "name": "data",
                    "type": "timeseries",
                    "format": "csv",
                    "size_bytes": 1024,
                    "download_url": "https://example.com/data.csv",
                    "hash": "def456",
                    "filename": "test.csv",
                    "timeseries_name": "test_series",
                    "shape": "wide",
                    "content_hash": "ghi789",
                }
            ],
        }

    @respx.mock
    def test_resolve_version_explicit(self, api_backend, mock_volume_detail):
        """Test resolve_version with explicit version and edition."""
        respx.get(f"{TEST_BASE_URL}/volumes/test").mock(
            return_value=httpx.Response(200, json=mock_volume_detail)
        )

        version, edition = api_backend.resolve_version("test", "v1.0.0", 1)
        assert version == "v1.0.0"
        assert edition == 1

    @respx.mock
    def test_resolve_version_latest_version(self, api_backend, mock_volume_detail):
        """Test resolve_version with version=None resolves to latest published."""
        respx.get(f"{TEST_BASE_URL}/volumes/test").mock(
            return_value=httpx.Response(200, json=mock_volume_detail)
        )

        version, edition = api_backend.resolve_version("test", version=None, edition=1)
        # v1.1.0 is the latest published version
        assert version == "v1.1.0"
        assert edition == 1

    @respx.mock
    def test_resolve_version_latest_edition(self, api_backend, mock_volume_detail):
        """Test resolve_version with edition=None resolves to highest edition number."""
        respx.get(f"{TEST_BASE_URL}/volumes/test").mock(
            return_value=httpx.Response(200, json=mock_volume_detail)
        )

        version, edition = api_backend.resolve_version("test", "v1.0.0", edition=None)
        assert version == "v1.0.0"
        assert edition == 2  # Highest edition for v1.0.0

    @respx.mock
    def test_resolve_version_skips_private_versions(self, api_backend):
        """Test that versions with only draft editions are treated as private."""
        volume_detail = {
            "id": "vol_1",
            "name": "test",
            "description": "Test volume",
            "license": "MIT",
            "metadata": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "versions": [
                {
                    "version": "v1.0.0",
                    "editions": [
                        {
                            "edition": 1,
                            "status": "published",
                            "created_at": "2024-01-01T00:00:00Z",
                            "published_at": "2024-01-01T00:00:00Z",
                        }
                    ],
                },
                {
                    "version": "v2.0.0",
                    "editions": [
                        {
                            "edition": 1,
                            "status": "draft",
                            "created_at": "2024-01-01T00:00:00Z",
                            "published_at": None,
                        }
                    ],
                },
            ],
            "stats": {
                "total_versions": 2,
                "total_editions": 2,
                "total_resources": 0,
                "total_size_bytes": 0,
            },
        }

        respx.get(f"{TEST_BASE_URL}/volumes/test").mock(return_value=httpx.Response(200, json=volume_detail))

        version, edition = api_backend.resolve_version("test", version=None, edition=1)
        # v2.0.0 has only draft editions, so should resolve to v1.0.0
        assert version == "v1.0.0"
        assert edition == 1

    @respx.mock
    def test_resolve_version_unknown_book(self, api_backend):
        """Test resolve_version raises UnknownBook for NotFoundError."""
        respx.get(f"{TEST_BASE_URL}/volumes/missing").mock(
            return_value=httpx.Response(404, json={"detail": "Not found"})
        )

        with pytest.raises(UnknownBook, match="No metadata for 'missing'"):
            api_backend.resolve_version("missing", "v1.0.0", 1)

    @respx.mock
    def test_resolve_version_unknown_version(self, api_backend, mock_volume_detail):
        """Test resolve_version raises UnknownVersion for missing version."""
        respx.get(f"{TEST_BASE_URL}/volumes/test").mock(
            return_value=httpx.Response(200, json=mock_volume_detail)
        )

        with pytest.raises(UnknownVersion):
            api_backend.resolve_version("test", "v9.9.9", 1)

    @respx.mock
    def test_resolve_version_unknown_edition(self, api_backend, mock_volume_detail):
        """Test resolve_version raises UnknownEdition for missing edition."""
        respx.get(f"{TEST_BASE_URL}/volumes/test").mock(
            return_value=httpx.Response(200, json=mock_volume_detail)
        )

        with pytest.raises(UnknownEdition):
            api_backend.resolve_version("test", "v1.0.0", 999)

    @respx.mock
    def test_resolve_version_no_published_versions(self, api_backend):
        """Test resolve_version raises ValueError when no published versions exist."""
        volume_detail = {
            "id": "vol_1",
            "name": "test",
            "description": "Test volume",
            "license": "MIT",
            "metadata": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "versions": [
                {
                    "version": "v1.0.0",
                    "editions": [
                        {
                            "edition": 1,
                            "status": "draft",
                            "created_at": "2024-01-01T00:00:00Z",
                            "published_at": None,
                        }
                    ],
                }
            ],
            "stats": {
                "total_versions": 1,
                "total_editions": 1,
                "total_resources": 0,
                "total_size_bytes": 0,
            },
        }

        respx.get(f"{TEST_BASE_URL}/volumes/test").mock(return_value=httpx.Response(200, json=volume_detail))

        with pytest.raises(ValueError, match="No published volumes"):
            api_backend.resolve_version("test", version=None, edition=1)

    @respx.mock
    def test_list_versions(self, api_backend, mock_volume_detail):
        """Test list_versions returns only versions with published editions."""
        respx.get(f"{TEST_BASE_URL}/volumes/test").mock(
            return_value=httpx.Response(200, json=mock_volume_detail)
        )

        versions = api_backend.list_versions("test")
        assert versions == ["v1.0.0", "v1.1.0"]

    @respx.mock
    def test_list_versions_filters_draft_only(self, api_backend):
        """Test list_versions filters out versions with only draft editions."""
        volume_detail = {
            "id": "vol_1",
            "name": "test",
            "description": "Test volume",
            "license": "MIT",
            "metadata": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "versions": [
                {
                    "version": "v1.0.0",
                    "editions": [
                        {
                            "edition": 1,
                            "status": "published",
                            "created_at": "2024-01-01T00:00:00Z",
                            "published_at": "2024-01-01T00:00:00Z",
                        }
                    ],
                },
                {
                    "version": "v2.0.0",
                    "editions": [
                        {
                            "edition": 1,
                            "status": "draft",
                            "created_at": "2024-01-01T00:00:00Z",
                            "published_at": None,
                        }
                    ],
                },
            ],
            "stats": {
                "total_versions": 2,
                "total_editions": 2,
                "total_resources": 0,
                "total_size_bytes": 0,
            },
        }

        respx.get(f"{TEST_BASE_URL}/volumes/test").mock(return_value=httpx.Response(200, json=volume_detail))

        versions = api_backend.list_versions("test")
        assert versions == ["v1.0.0"]
        # v2.0.0 has only draft editions and should be excluded

    @respx.mock
    def test_list_versions_unknown_book(self, api_backend):
        """Test list_versions raises UnknownBook for NotFoundError."""
        respx.get(f"{TEST_BASE_URL}/volumes/missing").mock(
            return_value=httpx.Response(404, json={"detail": "Not found"})
        )

        with pytest.raises(UnknownBook, match="No metadata for 'missing'"):
            api_backend.list_versions("missing")

    @respx.mock
    def test_fetch_datapackage(self, api_backend, mock_book_response, tmp_path):
        """Test fetch_datapackage creates datapackage.json from BookResponse."""
        respx.get(f"{TEST_BASE_URL}/volumes/test/books/v1.0.0").mock(
            return_value=httpx.Response(200, json=mock_book_response)
        )

        local_path = tmp_path / "test" / "datapackage.json"
        result_path = api_backend.fetch_datapackage("test", "v1.0.0", 1, local_path)

        assert result_path == local_path
        assert local_path.exists()

        with open(local_path) as f:
            data = json.load(f)
            assert data["name"] == "test"
            assert data["version"] == "v1.0.0"
            assert data["edition"] == 1
            assert data["description"] == "Test book"
            assert data["private"] is False
            assert len(data["resources"]) == 1

            # Check enriched resource fields
            resource = data["resources"][0]
            assert resource["name"] == "data"
            assert resource["format"] == "csv"
            assert resource["filename"] == "test.csv"
            assert resource["hash"] == "def456"
            assert resource["download_url"] == "https://example.com/data.csv"
            assert resource["timeseries_name"] == "test_series"
            assert resource["shape"] == "wide"
            assert resource["content_hash"] == "ghi789"

    @respx.mock
    def test_fetch_datapackage_unknown_version(self, api_backend, tmp_path):
        """Test fetch_datapackage raises UnknownVersion for NotFoundError."""
        respx.get(f"{TEST_BASE_URL}/volumes/test/books/v9.9.9").mock(
            return_value=httpx.Response(404, json={"detail": "Not found"})
        )

        local_path = tmp_path / "datapackage.json"

        with pytest.raises(UnknownVersion):
            api_backend.fetch_datapackage("test", "v9.9.9", 1, local_path)

    @respx.mock
    def test_download_resource(self, api_backend, mock_book_response, tmp_path, requests_mock):
        """Test download_resource uses API-provided download URL."""
        # Use a copy with hash=None so pooch doesn't verify hash against content
        book_no_hash = copy.deepcopy(mock_book_response)
        book_no_hash["resources"][0]["hash"] = None
        respx.get(f"{TEST_BASE_URL}/volumes/test/books/v1.0.0").mock(
            return_value=httpx.Response(200, json=book_no_hash)
        )

        # Mock the actual file download
        requests_mock.get(
            "https://example.com/data.csv",
            text="column1,column2\n1,2\n3,4",
        )

        local_path = tmp_path / "test.csv"
        api_backend.download_resource("test", "v1.0.0", 1, "test.csv", local_path)

        assert local_path.exists()
        content = local_path.read_text()
        assert "column1,column2" in content

    @respx.mock
    def test_download_resource_missing_file(self, api_backend, mock_book_response, tmp_path):
        """Test download_resource raises ValueError for missing resource."""
        respx.get(f"{TEST_BASE_URL}/volumes/test/books/v1.0.0").mock(
            return_value=httpx.Response(200, json=mock_book_response)
        )

        with pytest.raises(ValueError, match=r"Resource 'missing\.csv' not found"):
            api_backend.download_resource("test", "v1.0.0", 1, "missing.csv", tmp_path / "missing.csv")

    @respx.mock
    def test_list_volumes(self, api_backend):
        """Test list_volumes returns all volume names."""
        volume_list = {
            "items": [
                {
                    "id": "vol_1",
                    "name": "test1",
                    "description": "Test 1",
                    "license": "MIT",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "latest_version": "v1.0.0",
                    "latest_edition": 1,
                    "resource_types": ["timeseries"],
                },
                {
                    "id": "vol_2",
                    "name": "test2",
                    "description": "Test 2",
                    "license": "MIT",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "latest_version": "v2.0.0",
                    "latest_edition": 1,
                    "resource_types": ["tabular"],
                },
            ],
            "total": 2,
            "limit": 100,
            "offset": 0,
            "has_more": False,
        }

        respx.get(f"{TEST_BASE_URL}/volumes").mock(return_value=httpx.Response(200, json=volume_list))

        volumes = api_backend.list_volumes()
        assert volumes == ["test1", "test2"]

    @respx.mock
    def test_list_volumes_pagination(self, api_backend):
        """Test list_volumes handles pagination correctly."""
        # First page
        page1 = {
            "items": [
                {
                    "id": "vol_1",
                    "name": "test1",
                    "description": "Test 1",
                    "license": "MIT",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "latest_version": "v1.0.0",
                    "latest_edition": 1,
                    "resource_types": ["timeseries"],
                }
            ],
            "total": 2,
            "limit": 1,
            "offset": 0,
            "has_more": True,
        }

        # Second page
        page2 = {
            "items": [
                {
                    "id": "vol_2",
                    "name": "test2",
                    "description": "Test 2",
                    "license": "MIT",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "latest_version": "v2.0.0",
                    "latest_edition": 1,
                    "resource_types": ["tabular"],
                }
            ],
            "total": 2,
            "limit": 1,
            "offset": 1,
            "has_more": False,
        }

        respx.get(f"{TEST_BASE_URL}/volumes", params={"limit": 100, "offset": 0}).mock(
            return_value=httpx.Response(200, json=page1)
        )
        respx.get(f"{TEST_BASE_URL}/volumes", params={"limit": 100, "offset": 100}).mock(
            return_value=httpx.Response(200, json=page2)
        )

        volumes = api_backend.list_volumes()
        assert volumes == ["test1", "test2"]
