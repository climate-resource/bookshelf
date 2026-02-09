"""HTTP client for bookshelf-platform API."""

from collections.abc import Callable
from http import HTTPStatus
from typing import Any

import httpx

from bookshelf.api.errors import APIError, AuthenticationError, NotFoundError, ServerError
from bookshelf.api.schemas import (
    BookListResponse,
    BookResponse,
    BookStatus,
    VolumeDetailResponse,
    VolumeListResponse,
)


class BookshelfAPIClient:
    """Synchronous HTTP client for bookshelf-platform API.

    Handles authentication, request formatting, and error handling.
    Supports automatic token refresh on 401 responses via an optional callback.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
        on_token_refresh: Callable[[], str | None] | None = None,
    ):
        """Initialize API client.

        Args:
            base_url: Base URL of the API (e.g., "https://api.bookshelf.example.com")
            token: Optional bearer token for authentication
            timeout: Request timeout in seconds
            on_token_refresh: Optional callback that attempts to refresh the token.
                Should return a new access token string, or None if refresh fails.
                Called automatically on 401 responses.
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._on_token_refresh = on_token_refresh
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

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an HTTP request with automatic 401 retry via token refresh.

        On a 401 response, if an ``on_token_refresh`` callback is configured,
        it will be called to obtain a new token and the request retried once.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: URL path relative to base_url
            **kwargs: Additional arguments passed to httpx.Client.request()

        Returns
        -------
            httpx.Response on success

        Raises
        ------
            AuthenticationError: If 401 and refresh fails or is unavailable
            NotFoundError: For 404 responses
            ServerError: For 5xx responses
            APIError: For other error responses
        """
        url = f"{self.base_url}{path}"
        kwargs.setdefault("headers", self._headers())

        response = self._client.request(method, url, **kwargs)

        if response.is_success:
            return response

        # On 401, try refreshing the token once
        if response.status_code == HTTPStatus.UNAUTHORIZED and self._on_token_refresh is not None:
            new_token = self._on_token_refresh()
            if new_token:
                self.token = new_token
                # Update Authorization header for retry
                kwargs["headers"] = self._headers()
                retry_response = self._client.request(method, url, **kwargs)
                if retry_response.is_success:
                    return retry_response
                # If retry also fails, raise from the retry response
                self._handle_error(retry_response)

        self._handle_error(response)

        # _handle_error always raises, but this satisfies the type checker
        raise APIError("Unexpected error")  # pragma: no cover

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
        response = self._request(
            "GET",
            "/volumes",
            params={"limit": limit, "offset": offset},
        )
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
        response = self._request("GET", f"/volumes/{name}")
        return VolumeDetailResponse(**response.json())

    def list_books(  # noqa: PLR0913
        self,
        volume_name: str,
        version: str | None = None,
        status: BookStatus | None = None,
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

        response = self._request(
            "GET",
            f"/volumes/{volume_name}/books",
            params=params,
        )
        return BookListResponse(**response.json())

    def get_book(
        self,
        volume_name: str,
        version: str,
        edition: int | None = None,
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

        response = self._request(
            "GET",
            f"/volumes/{volume_name}/books/{version}",
            params=params,
        )
        return BookResponse(**response.json())
