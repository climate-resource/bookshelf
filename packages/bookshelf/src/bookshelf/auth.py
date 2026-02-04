"""
Authentication and credential storage for Bookshelf API.

Handles storing and retrieving API credentials in a secure, cross-platform manner.
"""

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypedDict

from platformdirs import user_config_dir


class Credentials(TypedDict):
    """Type definition for stored credentials."""

    access_token: str
    token_type: str
    expires_at: datetime | None
    api_url: str


def get_credentials_path() -> Path:
    """
    Get path to credentials file using platformdirs.

    Returns
    -------
    Path
        Path to the credentials file (e.g., ~/.config/bookshelf/credentials.json)
    """
    config_dir = Path(user_config_dir("bookshelf"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "credentials.json"


def load_credentials() -> Credentials | None:
    """
    Load stored credentials from disk.

    Returns None if credentials are not found, expired, or corrupt.

    Returns
    -------
    Credentials | None
        Credentials dict if valid, None otherwise
    """
    creds_path = get_credentials_path()

    if not creds_path.exists():
        return None

    try:
        with creds_path.open("r") as f:
            data = json.load(f)

        # Convert expires_at string to datetime if present
        if "expires_at" in data and data["expires_at"] is not None:
            expires_at = datetime.fromisoformat(data["expires_at"])
            # Check if expired
            if expires_at <= datetime.now(timezone.utc):
                # Clear expired credentials
                clear_credentials()
                return None
            data["expires_at"] = expires_at
        else:
            data["expires_at"] = None

        # Validate required fields
        if not all(k in data for k in ["access_token", "token_type", "api_url"]):
            return None

        # Type assertion after validation
        return Credentials(
            access_token=data["access_token"],
            token_type=data["token_type"],
            expires_at=data["expires_at"],
            api_url=data["api_url"],
        )

    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        # Corrupt or invalid credentials
        return None


def save_credentials(
    access_token: str,
    token_type: str = "bearer",  # noqa: S107
    expires_in: int | None = None,
    api_url: str | None = None,
) -> None:
    """
    Save credentials to disk.

    The credentials file is created with 0600 permissions (user read/write only)
    for security.

    Parameters
    ----------
    access_token : str
        The access token
    token_type : str, optional
        Token type (default: "bearer")
    expires_in : int | None, optional
        Token expiry in seconds from now (default: None for no expiry)
    api_url : str | None, optional
        API base URL (default: None, uses get_api_url() default)
    """
    creds_path = get_credentials_path()

    # Calculate expiry time if provided
    expires_at = None
    if expires_in is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    credentials = {
        "access_token": access_token,
        "token_type": token_type,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "api_url": api_url or get_api_url(),
    }

    # Write credentials
    with creds_path.open("w") as f:
        json.dump(credentials, f, indent=2)

    # Set secure permissions (user read/write only)
    creds_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def clear_credentials() -> None:
    """
    Remove stored credentials.

    Deletes the credentials file if it exists.
    """
    creds_path = get_credentials_path()
    if creds_path.exists():
        creds_path.unlink()


def is_authenticated() -> bool:
    """
    Check if valid credentials exist.

    Checks both stored credentials and environment variable overrides.

    Returns
    -------
    bool
        True if valid credentials are available, False otherwise
    """
    # Check environment variable override
    if os.environ.get("BOOKSHELF_TOKEN"):
        return True

    # Check stored credentials
    creds = load_credentials()
    return creds is not None


def get_token() -> str | None:
    """
    Get current access token if valid, else None.

    Checks environment variable override first, then stored credentials.

    Returns
    -------
    str | None
        Access token if available and valid, None otherwise
    """
    # Environment variable takes precedence
    env_token = os.environ.get("BOOKSHELF_TOKEN")
    if env_token:
        return env_token

    # Try stored credentials
    creds = load_credentials()
    if creds:
        return creds["access_token"]

    return None


def get_api_url() -> str:
    """
    Get API URL from credentials, environment, or default.

    Precedence: BOOKSHELF_API_URL env var > stored credentials > default

    Returns
    -------
    str
        API base URL
    """
    # Environment variable takes precedence
    env_url = os.environ.get("BOOKSHELF_API_URL")
    if env_url:
        return env_url

    # Try stored credentials
    creds = load_credentials()
    if creds:
        return creds["api_url"]

    # Default URL
    return "https://bookshelf.climate-resource.com/api"
