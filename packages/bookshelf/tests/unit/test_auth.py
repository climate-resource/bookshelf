"""Unit tests for authentication and credential storage."""

# ruff: noqa: S105, S106 - Test tokens/passwords are intentionally hardcoded

import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from bookshelf.auth import (
    clear_credentials,
    get_api_url,
    get_credentials_path,
    get_token,
    is_authenticated,
    load_credentials,
    save_credentials,
)


@pytest.fixture
def mock_credentials_path(tmp_path, monkeypatch):
    """Mock the credentials path to use a temporary directory."""
    config_dir = tmp_path / "bookshelf"
    config_dir.mkdir(parents=True, exist_ok=True)
    creds_path = config_dir / "credentials.json"

    def mock_get_credentials_path():
        return creds_path

    monkeypatch.setattr("bookshelf.auth.get_credentials_path", mock_get_credentials_path)
    return creds_path


@pytest.fixture
def clean_env(monkeypatch):
    """Remove environment variables that affect auth."""
    monkeypatch.delenv("BOOKSHELF_TOKEN", raising=False)
    monkeypatch.delenv("BOOKSHELF_API_URL", raising=False)


class TestGetCredentialsPath:
    """Tests for get_credentials_path function."""

    def test_returns_path_object(self):
        """Should return a Path object."""
        result = get_credentials_path()
        assert isinstance(result, Path)

    def test_path_contains_bookshelf(self):
        """Should contain 'bookshelf' in the path."""
        result = get_credentials_path()
        assert "bookshelf" in str(result).lower()

    def test_path_ends_with_credentials_json(self):
        """Should end with credentials.json."""
        result = get_credentials_path()
        assert result.name == "credentials.json"


class TestSaveCredentials:
    """Tests for save_credentials function."""

    def test_creates_credentials_file(self, mock_credentials_path, clean_env):
        """Should create a credentials file."""
        save_credentials(
            access_token="test_token_123",
            token_type="bearer",
            api_url="https://test.example.com",
        )

        assert mock_credentials_path.exists()

    def test_writes_correct_json_structure(self, mock_credentials_path, clean_env):
        """Should write correct JSON structure."""
        save_credentials(
            access_token="test_token_123",
            token_type="bearer",
            expires_in=3600,
            api_url="https://test.example.com",
        )

        with mock_credentials_path.open("r") as f:
            data = json.load(f)

        assert data["access_token"] == "test_token_123"
        assert data["token_type"] == "bearer"
        assert data["api_url"] == "https://test.example.com"
        assert "expires_at" in data

    def test_sets_correct_file_permissions(self, mock_credentials_path, clean_env):
        """Should set file permissions to 0600 (user read/write only)."""
        save_credentials(access_token="test_token_123", api_url="https://test.example.com")

        file_mode = mock_credentials_path.stat().st_mode
        # Check that only user read and write bits are set
        assert file_mode & stat.S_IRUSR  # User read
        assert file_mode & stat.S_IWUSR  # User write
        assert not (file_mode & stat.S_IRGRP)  # No group read
        assert not (file_mode & stat.S_IWGRP)  # No group write
        assert not (file_mode & stat.S_IROTH)  # No other read
        assert not (file_mode & stat.S_IWOTH)  # No other write

    def test_calculates_expiry_time(self, mock_credentials_path, clean_env):
        """Should calculate correct expiry time from expires_in."""
        before = datetime.now(timezone.utc)
        save_credentials(
            access_token="test_token_123",
            expires_in=3600,
            api_url="https://test.example.com",
        )
        after = datetime.now(timezone.utc)

        with mock_credentials_path.open("r") as f:
            data = json.load(f)

        expires_at = datetime.fromisoformat(data["expires_at"])
        expected_min = before + timedelta(seconds=3600)
        expected_max = after + timedelta(seconds=3600)

        assert expected_min <= expires_at <= expected_max

    def test_no_expiry_when_expires_in_none(self, mock_credentials_path, clean_env):
        """Should set expires_at to None when expires_in is None."""
        save_credentials(
            access_token="test_token_123",
            api_url="https://test.example.com",
        )

        with mock_credentials_path.open("r") as f:
            data = json.load(f)

        assert data["expires_at"] is None

    def test_uses_default_api_url_when_not_provided(self, mock_credentials_path, clean_env):
        """Should use default API URL when not provided."""
        save_credentials(access_token="test_token_123")

        with mock_credentials_path.open("r") as f:
            data = json.load(f)

        # Default URL from get_api_url()
        assert "bookshelf" in data["api_url"].lower()

    def test_saves_refresh_token(self, mock_credentials_path, clean_env):
        """Should save refresh_token when provided."""
        save_credentials(
            access_token="test_token_123",
            api_url="https://test.example.com",
            refresh_token="refresh_abc",
        )

        with mock_credentials_path.open("r") as f:
            data = json.load(f)

        assert data["refresh_token"] == "refresh_abc"

    def test_refresh_token_none_by_default(self, mock_credentials_path, clean_env):
        """Should set refresh_token to None when not provided."""
        save_credentials(
            access_token="test_token_123",
            api_url="https://test.example.com",
        )

        with mock_credentials_path.open("r") as f:
            data = json.load(f)

        assert data["refresh_token"] is None


class TestLoadCredentials:
    """Tests for load_credentials function."""

    def test_returns_none_when_file_missing(self, mock_credentials_path, clean_env):
        """Should return None when credentials file doesn't exist."""
        result = load_credentials()
        assert result is None

    def test_loads_valid_credentials(self, mock_credentials_path, clean_env):
        """Should load valid credentials."""
        save_credentials(
            access_token="test_token_123",
            token_type="bearer",
            api_url="https://test.example.com",
        )

        creds = load_credentials()
        assert creds is not None
        assert creds["access_token"] == "test_token_123"
        assert creds["token_type"] == "bearer"
        assert creds["api_url"] == "https://test.example.com"
        assert creds["expires_at"] is None

    def test_converts_expires_at_to_datetime(self, mock_credentials_path, clean_env):
        """Should convert expires_at string to datetime object."""
        save_credentials(
            access_token="test_token_123",
            expires_in=3600,
            api_url="https://test.example.com",
        )

        creds = load_credentials()
        assert creds is not None
        assert isinstance(creds["expires_at"], datetime)

    def test_returns_none_for_expired_credentials_no_refresh(self, mock_credentials_path, clean_env):
        """Should return None and clear file for expired credentials without refresh token."""
        expired_time = datetime.now(timezone.utc) - timedelta(hours=1)
        credentials = {
            "access_token": "test_token_123",
            "token_type": "bearer",
            "expires_at": expired_time.isoformat(),
            "api_url": "https://test.example.com",
        }

        with mock_credentials_path.open("w") as f:
            json.dump(credentials, f)

        result = load_credentials()
        assert result is None
        assert not mock_credentials_path.exists()

    def test_returns_none_for_corrupt_json(self, mock_credentials_path, clean_env):
        """Should return None for corrupt JSON."""
        with mock_credentials_path.open("w") as f:
            f.write("not valid json{")

        result = load_credentials()
        assert result is None

    def test_returns_none_for_missing_required_fields(self, mock_credentials_path, clean_env):
        """Should return None when required fields are missing."""
        incomplete_creds = {
            "access_token": "test_token_123",
            # Missing token_type and api_url
        }

        with mock_credentials_path.open("w") as f:
            json.dump(incomplete_creds, f)

        result = load_credentials()
        assert result is None

    def test_loads_refresh_token(self, mock_credentials_path, clean_env):
        """Should load refresh_token when present."""
        save_credentials(
            access_token="test_token_123",
            api_url="https://test.example.com",
            refresh_token="refresh_abc",
        )

        creds = load_credentials()
        assert creds is not None
        assert creds["refresh_token"] == "refresh_abc"

    def test_backward_compat_no_refresh_token(self, mock_credentials_path, clean_env):
        """Should handle old credentials files without refresh_token."""
        old_creds = {
            "access_token": "test_token_123",
            "token_type": "bearer",
            "expires_at": None,
            "api_url": "https://test.example.com",
            # No refresh_token field
        }

        with mock_credentials_path.open("w") as f:
            json.dump(old_creds, f)

        creds = load_credentials()
        assert creds is not None
        assert creds["refresh_token"] is None

    def test_expired_credentials_attempts_refresh(self, mock_credentials_path, clean_env):
        """Should attempt refresh when credentials are expired and refresh token exists."""
        expired_time = datetime.now(timezone.utc) - timedelta(hours=1)
        credentials = {
            "access_token": "old_token",
            "token_type": "bearer",
            "expires_at": expired_time.isoformat(),
            "api_url": "https://test.example.com",
            "refresh_token": "refresh_abc",
        }

        with mock_credentials_path.open("w") as f:
            json.dump(credentials, f)

        # Mock _try_refresh to succeed
        new_creds = {
            "access_token": "new_token",
            "token_type": "bearer",
            "expires_at": None,
            "api_url": "https://test.example.com",
            "refresh_token": "new_refresh",
        }
        with patch("bookshelf.auth._try_refresh", return_value=new_creds) as mock_refresh:
            result = load_credentials()

        mock_refresh.assert_called_once_with("refresh_abc", api_url="https://test.example.com")
        assert result is not None
        assert result["access_token"] == "new_token"

    def test_expired_credentials_refresh_failure_clears(self, mock_credentials_path, clean_env):
        """Should clear credentials when refresh fails."""
        expired_time = datetime.now(timezone.utc) - timedelta(hours=1)
        credentials = {
            "access_token": "old_token",
            "token_type": "bearer",
            "expires_at": expired_time.isoformat(),
            "api_url": "https://test.example.com",
            "refresh_token": "refresh_abc",
        }

        with mock_credentials_path.open("w") as f:
            json.dump(credentials, f)

        with patch("bookshelf.auth._try_refresh", return_value=None):
            result = load_credentials()

        assert result is None
        assert not mock_credentials_path.exists()


class TestClearCredentials:
    """Tests for clear_credentials function."""

    def test_removes_credentials_file(self, mock_credentials_path, clean_env):
        """Should remove the credentials file."""
        save_credentials(access_token="test_token_123", api_url="https://test.example.com")
        assert mock_credentials_path.exists()

        clear_credentials()
        assert not mock_credentials_path.exists()

    def test_no_error_when_file_missing(self, mock_credentials_path, clean_env):
        """Should not raise error when file doesn't exist."""
        # Should not raise any exception
        clear_credentials()
        assert not mock_credentials_path.exists()


class TestIsAuthenticated:
    """Tests for is_authenticated function."""

    def test_returns_true_with_env_token(self, mock_credentials_path, monkeypatch):
        """Should return True when BOOKSHELF_TOKEN is set."""
        monkeypatch.setenv("BOOKSHELF_TOKEN", "env_token_123")

        result = is_authenticated()
        assert result is True

    def test_returns_true_with_valid_stored_credentials(self, mock_credentials_path, clean_env):
        """Should return True with valid stored credentials."""
        save_credentials(access_token="test_token_123", api_url="https://test.example.com")

        result = is_authenticated()
        assert result is True

    def test_returns_false_with_no_credentials(self, mock_credentials_path, clean_env):
        """Should return False when no credentials exist."""
        result = is_authenticated()
        assert result is False

    def test_returns_false_with_expired_credentials(self, mock_credentials_path, clean_env):
        """Should return False with expired credentials."""
        # Create expired credentials
        expired_time = datetime.now(timezone.utc) - timedelta(hours=1)
        credentials = {
            "access_token": "test_token_123",
            "token_type": "bearer",
            "expires_at": expired_time.isoformat(),
            "api_url": "https://test.example.com",
        }

        with mock_credentials_path.open("w") as f:
            json.dump(credentials, f)

        with patch("bookshelf.auth._try_refresh", return_value=None):
            result = is_authenticated()
        assert result is False


class TestGetToken:
    """Tests for get_token function."""

    def test_returns_env_token_when_set(self, mock_credentials_path, monkeypatch):
        """Should prioritize BOOKSHELF_TOKEN environment variable."""
        monkeypatch.setenv("BOOKSHELF_TOKEN", "env_token_123")
        save_credentials(access_token="stored_token_456", api_url="https://test.example.com")

        result = get_token()
        assert result == "env_token_123"

    def test_returns_stored_token_when_env_not_set(self, mock_credentials_path, clean_env):
        """Should return stored token when env var not set."""
        save_credentials(access_token="stored_token_456", api_url="https://test.example.com")

        result = get_token()
        assert result == "stored_token_456"

    def test_returns_none_when_no_credentials(self, mock_credentials_path, clean_env):
        """Should return None when no credentials available."""
        result = get_token()
        assert result is None

    def test_returns_none_for_expired_credentials(self, mock_credentials_path, clean_env):
        """Should return None for expired credentials."""
        # Create expired credentials
        expired_time = datetime.now(timezone.utc) - timedelta(hours=1)
        credentials = {
            "access_token": "test_token_123",
            "token_type": "bearer",
            "expires_at": expired_time.isoformat(),
            "api_url": "https://test.example.com",
        }

        with mock_credentials_path.open("w") as f:
            json.dump(credentials, f)

        with patch("bookshelf.auth._try_refresh", return_value=None):
            result = get_token()
        assert result is None

    def test_proactive_refresh_when_expiring_soon(self, mock_credentials_path, clean_env):
        """Should proactively refresh when token expires within 5 minutes."""
        # Token expires in 2 minutes (within the 5-minute window)
        save_credentials(
            access_token="old_token",
            expires_in=120,
            api_url="https://test.example.com",
            refresh_token="refresh_abc",
        )

        new_creds = {
            "access_token": "new_token",
            "token_type": "bearer",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "api_url": "https://test.example.com",
            "refresh_token": "new_refresh",
        }
        with patch("bookshelf.auth._try_refresh", return_value=new_creds) as mock_refresh:
            result = get_token()

        assert result == "new_token"
        mock_refresh.assert_called_once()

    def test_no_proactive_refresh_without_refresh_token(self, mock_credentials_path, clean_env):
        """Should not attempt refresh when no refresh token is available."""
        save_credentials(
            access_token="old_token",
            expires_in=120,
            api_url="https://test.example.com",
        )

        with patch("bookshelf.auth._try_refresh") as mock_refresh:
            result = get_token()

        assert result == "old_token"
        mock_refresh.assert_not_called()

    def test_proactive_refresh_failure_returns_current_token(self, mock_credentials_path, clean_env):
        """Should return current token if proactive refresh fails."""
        save_credentials(
            access_token="old_token",
            expires_in=120,
            api_url="https://test.example.com",
            refresh_token="refresh_abc",
        )

        with patch("bookshelf.auth._try_refresh", return_value=None):
            result = get_token()

        assert result == "old_token"


class TestGetApiUrl:
    """Tests for get_api_url function."""

    def test_returns_env_url_when_set(self, mock_credentials_path, monkeypatch):
        """Should prioritize BOOKSHELF_API_URL environment variable."""
        monkeypatch.setenv("BOOKSHELF_API_URL", "https://env.example.com/api")
        save_credentials(access_token="test_token", api_url="https://stored.example.com/api")

        result = get_api_url()
        assert result == "https://env.example.com/api"

    def test_returns_stored_url_when_env_not_set(self, mock_credentials_path, clean_env):
        """Should return stored URL when env var not set."""
        save_credentials(access_token="test_token", api_url="https://stored.example.com/api")

        result = get_api_url()
        assert result == "https://stored.example.com/api"

    def test_returns_default_url_when_no_credentials(self, mock_credentials_path, clean_env):
        """Should return default URL when no credentials exist."""
        result = get_api_url()
        assert "staging" in result or "bookshelf" in result.lower()
