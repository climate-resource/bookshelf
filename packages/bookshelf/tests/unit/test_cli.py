"""Unit tests for the Bookshelf CLI."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from click.testing import CliRunner

from bookshelf.cli import main


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    return CliRunner()


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
def api_env(monkeypatch):
    """Set up API environment (unauthenticated, for public access)."""
    monkeypatch.setenv("BOOKSHELF_API_URL", "https://test.example.com")


@pytest.fixture
def authenticated_env(mock_credentials_path, monkeypatch):
    """Set up authenticated environment."""
    import json

    credentials = {
        "access_token": "test_token_123",
        "token_type": "bearer",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "api_url": "https://test.example.com",
    }

    with mock_credentials_path.open("w") as f:
        json.dump(credentials, f)

    monkeypatch.setenv("BOOKSHELF_API_URL", "https://test.example.com")


class TestLoginCommand:
    """Tests for the login command."""

    @respx.mock
    def test_login_success(self, runner, mock_credentials_path, monkeypatch):
        """Should successfully login and save credentials."""
        monkeypatch.setenv("BOOKSHELF_API_URL", "https://test.example.com")

        respx.post("https://test.example.com/auth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "new_token_123",
                    "token_type": "bearer",
                    "expires_in": 3600,
                },
            )
        )

        result = runner.invoke(
            main,
            ["auth", "login"],
            input="testuser\ntestpassword\n",
        )

        assert result.exit_code == 0
        assert "successful" in result.output.lower() or "success" in result.output.lower()

        # Verify credentials were saved
        assert mock_credentials_path.exists()

    @respx.mock
    def test_login_invalid_credentials(self, runner, monkeypatch):
        """Should handle invalid credentials."""
        monkeypatch.setenv("BOOKSHELF_API_URL", "https://test.example.com")

        respx.post("https://test.example.com/auth/token").mock(
            return_value=httpx.Response(
                401,
                json={"detail": "Invalid username or password"},
            )
        )

        result = runner.invoke(
            main,
            ["auth", "login"],
            input="baduser\nbadpassword\n",
        )

        assert result.exit_code != 0

    @respx.mock
    def test_login_network_error(self, runner, monkeypatch):
        """Should handle network errors during login."""
        monkeypatch.setenv("BOOKSHELF_API_URL", "https://test.example.com")

        respx.post("https://test.example.com/auth/token").mock(
            side_effect=httpx.ConnectError("Connection failed")
        )

        result = runner.invoke(
            main,
            ["auth", "login"],
            input="testuser\ntestpassword\n",
        )

        assert result.exit_code != 0


class TestLogoutCommand:
    """Tests for the logout command."""

    def test_logout_success(self, runner, authenticated_env, mock_credentials_path):
        """Should successfully logout and clear credentials."""
        result = runner.invoke(main, ["auth", "logout"])

        assert result.exit_code == 0
        assert "logged out" in result.output.lower() or "success" in result.output.lower()
        assert not mock_credentials_path.exists()

    def test_logout_when_not_logged_in(self, runner, mock_credentials_path):
        """Should handle logout when not logged in."""
        result = runner.invoke(main, ["auth", "logout"])

        # Should not error, just inform user
        assert result.exit_code == 0


class TestStatusCommand:
    """Tests for the status command."""

    def test_status_authenticated(self, runner, authenticated_env):
        """Should show authenticated status."""
        result = runner.invoke(main, ["auth", "status"])

        assert result.exit_code == 0
        assert "logged in" in result.output.lower() or "authenticated" in result.output.lower()

    def test_status_not_authenticated(self, runner, mock_credentials_path):
        """Should show not authenticated status."""
        result = runner.invoke(main, ["auth", "status"])

        assert result.exit_code == 0
        assert "not logged in" in result.output.lower() or "not authenticated" in result.output.lower()


class TestVolumesListCommand:
    """Tests for the volumes list command."""

    @respx.mock
    def test_volumes_list_success(self, runner, api_env):
        """Should list volumes successfully (public access)."""
        respx.get("https://test.example.com/volumes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "vol_1",
                            "name": "climate-data",
                            "description": "Climate datasets",
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
                },
            )
        )

        result = runner.invoke(main, ["volumes", "list"])

        assert result.exit_code == 0
        assert "climate-data" in result.output

    @respx.mock
    def test_volumes_list_empty(self, runner, api_env):
        """Should handle empty volume list."""
        respx.get("https://test.example.com/volumes").mock(
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

        result = runner.invoke(main, ["volumes", "list"])

        assert result.exit_code == 0


class TestVolumesShowCommand:
    """Tests for the volumes show command."""

    @respx.mock
    def test_volumes_show_success(self, runner, api_env):
        """Should show volume details successfully (public access)."""
        respx.get("https://test.example.com/volumes/climate-data").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "vol_1",
                    "name": "climate-data",
                    "description": "Climate datasets",
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
                },
            )
        )

        result = runner.invoke(main, ["volumes", "show", "climate-data"])

        assert result.exit_code == 0
        assert "climate-data" in result.output

    @respx.mock
    def test_volumes_show_not_found(self, runner, api_env):
        """Should handle volume not found."""
        respx.get("https://test.example.com/volumes/missing").mock(
            return_value=httpx.Response(404, json={"detail": "Volume not found"})
        )

        result = runner.invoke(main, ["volumes", "show", "missing"])

        assert result.exit_code != 0


class TestBooksListCommand:
    """Tests for the books list command."""

    @respx.mock
    def test_books_list_success(self, runner, api_env):
        """Should list books successfully (public access)."""
        respx.get("https://test.example.com/volumes/climate-data/books").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "book_1",
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
                },
            )
        )

        result = runner.invoke(main, ["books", "list", "climate-data"])

        assert result.exit_code == 0
        assert "v1.0.0" in result.output


class TestBooksShowCommand:
    """Tests for the books show command."""

    @respx.mock
    def test_books_show_success(self, runner, api_env):
        """Should show book details successfully (public access)."""
        respx.get("https://test.example.com/volumes/climate-data/books/v1.0.0").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "book_1",
                    "volume_id": "vol_1",
                    "version": "v1.0.0",
                    "edition": 1,
                    "description": "Climate data v1.0.0",
                    "status": "published",
                    "private": False,
                    "metadata": {"author": "Climate Resource"},
                    "data_dictionary": [],
                    "hash": "abc123",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "published_at": "2024-01-01T12:00:00Z",
                    "resources": [
                        {
                            "id": "res_1",
                            "name": "data.csv",
                            "type": "timeseries",
                            "format": "csv",
                            "size_bytes": 1024,
                        }
                    ],
                },
            )
        )

        result = runner.invoke(main, ["books", "show", "climate-data", "v1.0.0"])

        assert result.exit_code == 0
        assert "v1.0.0" in result.output

    @respx.mock
    def test_books_show_with_edition(self, runner, api_env):
        """Should show specific edition."""
        route = respx.get("https://test.example.com/volumes/climate-data/books/v1.0.0").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "book_1",
                    "volume_id": "vol_1",
                    "version": "v1.0.0",
                    "edition": 2,
                    "description": "Climate data v1.0.0 e002",
                    "status": "published",
                    "private": False,
                    "metadata": {},
                    "data_dictionary": [],
                    "hash": "abc123",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "published_at": "2024-01-01T12:00:00Z",
                    "resources": [],
                },
            )
        )

        result = runner.invoke(main, ["books", "show", "climate-data", "v1.0.0", "--edition", "2"])

        assert result.exit_code == 0
        assert route.called
        # Check edition was in query params
        request = route.calls.last.request
        assert "edition=2" in str(request.url)

    @respx.mock
    def test_books_show_not_found(self, runner, api_env):
        """Should handle book not found."""
        respx.get("https://test.example.com/volumes/climate-data/books/v99.0.0").mock(
            return_value=httpx.Response(404, json={"detail": "Book not found"})
        )

        result = runner.invoke(main, ["books", "show", "climate-data", "v99.0.0"])

        assert result.exit_code != 0


class TestCLIHelp:
    """Tests for CLI help output."""

    def test_main_help(self, runner):
        """Should display main help."""
        result = runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "bookshelf" in result.output.lower()

    def test_auth_help(self, runner):
        """Should display auth subcommand help."""
        result = runner.invoke(main, ["auth", "--help"])

        assert result.exit_code == 0
        assert "login" in result.output.lower()

    def test_volumes_help(self, runner):
        """Should display volumes subcommand help."""
        result = runner.invoke(main, ["volumes", "--help"])

        assert result.exit_code == 0
        assert "list" in result.output.lower()
        assert "show" in result.output.lower()

    def test_books_help(self, runner):
        """Should display books subcommand help."""
        result = runner.invoke(main, ["books", "--help"])

        assert result.exit_code == 0
        assert "list" in result.output.lower()
        assert "show" in result.output.lower()
