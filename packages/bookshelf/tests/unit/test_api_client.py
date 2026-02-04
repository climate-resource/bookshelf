"""Unit tests for the Bookshelf API client."""

# ruff: noqa: S105, S106 - Test tokens/passwords are intentionally hardcoded

import httpx
import pytest
import respx

from bookshelf.api import BookshelfAPIClient
from bookshelf.api.errors import (
    APIError,
    AuthenticationError,
    NotFoundError,
    ServerError,
)
from bookshelf.api.schemas import (
    BookListResponse,
    BookResponse,
    BookStatus,
    TokenResponse,
    VolumeDetailResponse,
    VolumeListResponse,
)

# Base URL for tests
TEST_BASE_URL = "https://test.example.com"


@pytest.fixture
def api_client():
    """Create an API client for testing."""
    return BookshelfAPIClient(base_url=TEST_BASE_URL, token="test_token_123")


@pytest.fixture
def mock_volume_list_response():
    """Sample volume list response."""
    return {
        "items": [
            {
                "id": "vol_123",
                "name": "test-volume",
                "description": "Test volume",
                "license": "MIT",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
                "latest_version": "v1.0.0",
                "latest_edition": 1,
                "resource_types": ["timeseries"],
            }
        ],
        "total": 1,
        "limit": 100,
        "offset": 0,
        "has_more": False,
    }


@pytest.fixture
def mock_volume_detail_response():
    """Sample volume detail response."""
    return {
        "id": "vol_123",
        "name": "test-volume",
        "description": "Test volume",
        "license": "MIT",
        "metadata": {},
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-02T00:00:00Z",
        "versions": [
            {
                "version": "v1.0.0",
                "editions": [
                    {
                        "edition": 1,
                        "status": "published",
                        "created_at": "2024-01-01T00:00:00Z",
                        "published_at": "2024-01-01T12:00:00Z",
                    }
                ],
            }
        ],
        "stats": {
            "total_versions": 1,
            "total_editions": 1,
            "total_resources": 5,
            "total_size_bytes": 1024000,
        },
    }


@pytest.fixture
def mock_book_list_response():
    """Sample book list response."""
    return {
        "items": [
            {
                "id": "book_456",
                "version": "v1.0.0",
                "edition": 1,
                "status": "published",
                "private": False,
                "created_at": "2024-01-01T00:00:00Z",
                "published_at": "2024-01-01T12:00:00Z",
                "resource_count": 3,
            }
        ],
        "total": 1,
        "limit": 100,
        "offset": 0,
        "has_more": False,
    }


@pytest.fixture
def mock_book_detail_response():
    """Sample book detail response."""
    return {
        "id": "book_456",
        "volume_id": "vol_123",
        "version": "v1.0.0",
        "edition": 1,
        "description": "Test book",
        "status": "published",
        "private": False,
        "metadata": {"author": "Test Author"},
        "data_dictionary": [
            {
                "name": "temperature",
                "type": "float",
                "description": "Temperature in Celsius",
                "unit": "°C",
                "required": True,
            }
        ],
        "hash": "abc123def456",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "published_at": "2024-01-01T12:00:00Z",
        "resources": [
            {
                "id": "res_789",
                "name": "data.csv",
                "type": "timeseries",
                "format": "csv",
                "size_bytes": 1024,
            }
        ],
    }


class TestBookshelfAPIClientInit:
    """Tests for BookshelfAPIClient initialization."""

    def test_init_with_explicit_url(self):
        """Should initialize with explicit base URL."""
        client = BookshelfAPIClient(base_url="https://custom.example.com")
        assert client.base_url == "https://custom.example.com"

    def test_init_with_token(self):
        """Should initialize with token."""
        client = BookshelfAPIClient(base_url=TEST_BASE_URL, token="my_token")
        assert client.token == "my_token"

    def test_init_without_token(self):
        """Should allow initialization without token."""
        client = BookshelfAPIClient(base_url=TEST_BASE_URL)
        assert client.token is None

    def test_sets_authorization_header_when_token_provided(self):
        """Should set Authorization header when token is provided."""
        client = BookshelfAPIClient(base_url=TEST_BASE_URL, token="test_token_123")
        headers = client._headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test_token_123"


class TestListVolumes:
    """Tests for list_volumes method."""

    @respx.mock
    def test_list_volumes_success(self, api_client, mock_volume_list_response):
        """Should list volumes successfully."""
        route = respx.get(f"{TEST_BASE_URL}/volumes").mock(
            return_value=httpx.Response(200, json=mock_volume_list_response)
        )

        result = api_client.list_volumes()

        assert route.called
        assert isinstance(result, VolumeListResponse)
        assert len(result.items) == 1
        # items are VolumeListItem models, not dicts
        assert result.items[0].name == "test-volume"
        assert result.total == 1

    @respx.mock
    def test_list_volumes_with_pagination(self, api_client, mock_volume_list_response):
        """Should support pagination parameters."""
        route = respx.get(f"{TEST_BASE_URL}/volumes").mock(
            return_value=httpx.Response(200, json=mock_volume_list_response)
        )

        api_client.list_volumes(limit=50, offset=10)

        assert route.called
        # Check that query params were sent
        request = route.calls.last.request
        assert "limit=50" in str(request.url)
        assert "offset=10" in str(request.url)

    @respx.mock
    def test_list_volumes_401_raises_auth_error(self, api_client):
        """Should raise AuthenticationError on 401."""
        respx.get(f"{TEST_BASE_URL}/volumes").mock(
            return_value=httpx.Response(401, json={"detail": "Invalid token"})
        )

        with pytest.raises(AuthenticationError, match="Invalid token"):
            api_client.list_volumes()

    @respx.mock
    def test_list_volumes_500_raises_server_error(self, api_client):
        """Should raise ServerError on 500."""
        respx.get(f"{TEST_BASE_URL}/volumes").mock(
            return_value=httpx.Response(500, json={"detail": "Internal server error"})
        )

        with pytest.raises(ServerError, match="Internal server error"):
            api_client.list_volumes()


class TestGetVolume:
    """Tests for get_volume method."""

    @respx.mock
    def test_get_volume_success(self, api_client, mock_volume_detail_response):
        """Should get volume details successfully."""
        route = respx.get(f"{TEST_BASE_URL}/volumes/test-volume").mock(
            return_value=httpx.Response(200, json=mock_volume_detail_response)
        )

        result = api_client.get_volume("test-volume")

        assert route.called
        assert isinstance(result, VolumeDetailResponse)
        assert result.name == "test-volume"
        assert result.stats.total_versions == 1

    @respx.mock
    def test_get_volume_404_raises_not_found(self, api_client):
        """Should raise NotFoundError on 404."""
        respx.get(f"{TEST_BASE_URL}/volumes/missing").mock(
            return_value=httpx.Response(404, json={"detail": "Volume not found"})
        )

        with pytest.raises(NotFoundError, match="Volume not found"):
            api_client.get_volume("missing")


class TestListBooks:
    """Tests for list_books method."""

    @respx.mock
    def test_list_books_success(self, api_client, mock_book_list_response):
        """Should list books successfully."""
        route = respx.get(f"{TEST_BASE_URL}/volumes/test-volume/books").mock(
            return_value=httpx.Response(200, json=mock_book_list_response)
        )

        result = api_client.list_books("test-volume")

        assert route.called
        assert isinstance(result, BookListResponse)
        assert len(result.items) == 1
        assert result.items[0].version == "v1.0.0"

    @respx.mock
    def test_list_books_with_filters(self, api_client, mock_book_list_response):
        """Should support status and version filters."""
        route = respx.get(f"{TEST_BASE_URL}/volumes/test-volume/books").mock(
            return_value=httpx.Response(200, json=mock_book_list_response)
        )

        api_client.list_books(
            "test-volume",
            status=BookStatus.PUBLISHED,
            version="v1.0.0",
            limit=25,
            offset=5,
        )

        assert route.called
        request = route.calls.last.request
        assert "status=published" in str(request.url)
        assert "version=v1.0.0" in str(request.url)
        assert "limit=25" in str(request.url)
        assert "offset=5" in str(request.url)

    @respx.mock
    def test_list_books_with_pagination(self, api_client, mock_book_list_response):
        """Should support pagination."""
        route = respx.get(f"{TEST_BASE_URL}/volumes/test-volume/books").mock(
            return_value=httpx.Response(200, json=mock_book_list_response)
        )

        api_client.list_books("test-volume", limit=10, offset=20)

        assert route.called
        request = route.calls.last.request
        assert "limit=10" in str(request.url)
        assert "offset=20" in str(request.url)


class TestGetBook:
    """Tests for get_book method."""

    @respx.mock
    def test_get_book_with_edition(self, api_client, mock_book_detail_response):
        """Should get book with specific edition."""
        route = respx.get(f"{TEST_BASE_URL}/volumes/test-volume/books/v1.0.0").mock(
            return_value=httpx.Response(200, json=mock_book_detail_response)
        )

        result = api_client.get_book("test-volume", "v1.0.0", edition=1)

        assert route.called
        assert isinstance(result, BookResponse)
        assert result.version == "v1.0.0"
        assert result.edition == 1
        # Check edition was in query params
        request = route.calls.last.request
        assert "edition=1" in str(request.url)

    @respx.mock
    def test_get_book_latest_edition(self, api_client, mock_book_detail_response):
        """Should get latest edition when not specified."""
        route = respx.get(f"{TEST_BASE_URL}/volumes/test-volume/books/v1.0.0").mock(
            return_value=httpx.Response(200, json=mock_book_detail_response)
        )

        result = api_client.get_book("test-volume", "v1.0.0")

        assert route.called
        assert isinstance(result, BookResponse)

    @respx.mock
    def test_get_book_404_raises_not_found(self, api_client):
        """Should raise NotFoundError on 404."""
        respx.get(f"{TEST_BASE_URL}/volumes/test-volume/books/v99.0.0").mock(
            return_value=httpx.Response(404, json={"detail": "Book not found"})
        )

        with pytest.raises(NotFoundError, match="Book not found"):
            api_client.get_book("test-volume", "v99.0.0")


class TestErrorHandling:
    """Tests for error handling across all methods."""

    @respx.mock
    def test_401_unauthorized(self, api_client):
        """Should handle 401 Unauthorized."""
        respx.get(f"{TEST_BASE_URL}/volumes").mock(
            return_value=httpx.Response(401, json={"detail": "Token expired"})
        )

        with pytest.raises(AuthenticationError, match="Token expired"):
            api_client.list_volumes()

    @respx.mock
    def test_403_forbidden(self, api_client):
        """Should handle 403 Forbidden."""
        respx.get(f"{TEST_BASE_URL}/volumes/private-volume").mock(
            return_value=httpx.Response(403, json={"detail": "Access denied"})
        )

        with pytest.raises(APIError, match="Access denied"):
            api_client.get_volume("private-volume")

    @respx.mock
    def test_404_not_found(self, api_client):
        """Should handle 404 Not Found."""
        respx.get(f"{TEST_BASE_URL}/volumes/missing").mock(
            return_value=httpx.Response(404, json={"detail": "Resource not found"})
        )

        with pytest.raises(NotFoundError, match="Resource not found"):
            api_client.get_volume("missing")

    @respx.mock
    def test_429_rate_limit(self, api_client):
        """Should handle 429 Rate Limit."""
        respx.get(f"{TEST_BASE_URL}/volumes").mock(
            return_value=httpx.Response(429, json={"detail": "Rate limit exceeded"})
        )

        with pytest.raises(APIError, match="Rate limit exceeded"):
            api_client.list_volumes()

    @respx.mock
    def test_500_internal_error(self, api_client):
        """Should handle 500 Internal Server Error."""
        respx.get(f"{TEST_BASE_URL}/volumes").mock(
            return_value=httpx.Response(500, json={"detail": "Internal error"})
        )

        with pytest.raises(ServerError, match="Internal error"):
            api_client.list_volumes()


class TestAuthenticate:
    """Tests for authenticate method."""

    @respx.mock
    def test_authenticate_success(self):
        """Should authenticate and set token."""
        client = BookshelfAPIClient(base_url=TEST_BASE_URL)

        route = respx.post(f"{TEST_BASE_URL}/auth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "new_token_456",
                    "token_type": "bearer",
                    "expires_in": 3600,
                },
            )
        )

        result = client.authenticate(username="test", password="secret")

        assert route.called
        assert isinstance(result, TokenResponse)
        assert result.access_token == "new_token_456"
        assert client.token == "new_token_456"

    @respx.mock
    def test_authenticate_failure(self):
        """Should raise AuthenticationError on invalid credentials."""
        client = BookshelfAPIClient(base_url=TEST_BASE_URL)

        respx.post(f"{TEST_BASE_URL}/auth/token").mock(
            return_value=httpx.Response(401, json={"detail": "Invalid credentials"})
        )

        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            client.authenticate(username="test", password="wrong")


class TestContextManager:
    """Tests for context manager support."""

    @respx.mock
    def test_can_use_as_context_manager(self):
        """Should support context manager protocol."""
        route = respx.get(f"{TEST_BASE_URL}/volumes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [],
                    "total": 0,
                    "limit": 100,
                    "offset": 0,
                    "has_more": False,
                },
            )
        )

        with BookshelfAPIClient(base_url=TEST_BASE_URL, token="test") as client:
            client.list_volumes()

        assert route.called

    def test_close_closes_http_client(self):
        """Should close underlying HTTP client."""
        client = BookshelfAPIClient(base_url=TEST_BASE_URL)
        client.close()
        # Verify client is closed (accessing it would raise)
        assert client._client.is_closed
