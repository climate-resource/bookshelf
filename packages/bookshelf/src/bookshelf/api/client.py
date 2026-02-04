"""HTTP client for bookshelf-platform API."""

from http import HTTPStatus
from typing import Any, Optional

import httpx

from bookshelf.api.errors import APIError, AuthenticationError, NotFoundError, ServerError
from bookshelf.api.schemas import (
    BookListResponse,
    BookResponse,
    BookStatus,
    TokenResponse,
    VolumeDetailResponse,
    VolumeListResponse,
)


class BookshelfAPIClient:
    """Synchronous HTTP client for bookshelf-platform API.

    Handles authentication, request formatting, and error handling.
    """

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """Initialize API client.

        Args:
            base_url: Base URL of the API (e.g., "https://api.bookshelf.example.com")
            token: Optional bearer token for authentication
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def __enter__(self) -> "BookshelfAPIClient":
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def _headers(self) -> dict[str, str]:
        """Build request headers."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _handle_error(self, response: httpx.Response) -> None:
        """Handle HTTP error responses.

        Args:
            response: HTTP response object

        Raises
        ------
            AuthenticationError: For 401 responses
            NotFoundError: For 404 responses
            ServerError: For 5xx responses
            APIError: For other error responses
        """
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            raise AuthenticationError(detail)
        elif response.status_code == HTTPStatus.NOT_FOUND:
            raise NotFoundError(detail)
        elif response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise ServerError(detail, status_code=response.status_code)
        else:
            raise APIError(detail, status_code=response.status_code)

    def authenticate(self, username: str, password: str) -> TokenResponse:
        """Authenticate and obtain access token.

        Args:
            username: Username or email
            password: Password

        Returns
        -------
            TokenResponse containing access token and metadata

        Raises
        ------
            AuthenticationError: If credentials are invalid
        """
        response = self._client.post(
            f"{self.base_url}/api/auth/token",
            data={
                "username": username,
                "password": password,
                "grant_type": "password",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if not response.is_success:
            self._handle_error(response)

        token_data = TokenResponse(**response.json())
        self.token = token_data.access_token
        return token_data

    def list_volumes(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> VolumeListResponse:
        """List all volumes.

        Args:
            limit: Maximum items to return (1-1000)
            offset: Number of items to skip

        Returns
        -------
            Paginated list of volumes
        """
        response = self._client.get(
            f"{self.base_url}/api/volumes",
            params={"limit": limit, "offset": offset},
            headers=self._headers(),
        )

        if not response.is_success:
            self._handle_error(response)

        return VolumeListResponse(**response.json())

    def get_volume(self, name: str) -> VolumeDetailResponse:
        """Get detailed volume information.

        Args:
            name: Volume name

        Returns
        -------
            Volume detail with version history and stats

        Raises
        ------
            NotFoundError: If volume does not exist
        """
        response = self._client.get(
            f"{self.base_url}/api/volumes/{name}",
            headers=self._headers(),
        )

        if not response.is_success:
            self._handle_error(response)

        return VolumeDetailResponse(**response.json())

    def list_books(  # noqa: PLR0913
        self,
        volume_name: str,
        version: Optional[str] = None,
        status: Optional[BookStatus] = None,
        latest_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> BookListResponse:
        """List books in a volume.

        Args:
            volume_name: Volume name
            version: Filter by version (optional)
            status: Filter by status (optional)
            latest_only: Return only latest edition per version
            limit: Maximum items to return (1-1000)
            offset: Number of items to skip

        Returns
        -------
            Paginated list of books
        """
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "latest_only": latest_only,
        }
        if version:
            params["version"] = version
        if status:
            params["status"] = status.value

        response = self._client.get(
            f"{self.base_url}/api/volumes/{volume_name}/books",
            params=params,
            headers=self._headers(),
        )

        if not response.is_success:
            self._handle_error(response)

        return BookListResponse(**response.json())

    def get_book(
        self,
        volume_name: str,
        version: str,
        edition: Optional[int] = None,
    ) -> BookResponse:
        """Get book by version.

        Args:
            volume_name: Volume name
            version: Book version
            edition: Specific edition (defaults to latest if not specified)

        Returns
        -------
            Full book details including resources

        Raises
        ------
            NotFoundError: If book does not exist
        """
        params = {}
        if edition is not None:
            params["edition"] = edition

        response = self._client.get(
            f"{self.base_url}/api/volumes/{volume_name}/books/{version}",
            params=params,
            headers=self._headers(),
        )

        if not response.is_success:
            self._handle_error(response)

        return BookResponse(**response.json())
