"""API-specific exceptions."""


class APIError(Exception):
    """Base exception for API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AuthenticationError(APIError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401)


class NotFoundError(APIError):
    """Raised when a resource is not found."""

    def __init__(self, message: str):
        super().__init__(message, status_code=404)


class ServerError(APIError):
    """Raised when the server returns a 5xx error."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message, status_code=status_code)
