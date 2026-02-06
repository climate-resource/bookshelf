"""Unit tests for OAuth authentication flows."""

# ruff: noqa: S105 - Test tokens are intentionally hardcoded

import base64
import hashlib
import json
from unittest.mock import patch

import httpx
import pytest
import respx

from bookshelf.oauth import (
    DeviceFlowInfo,
    OAuthError,
    _exchange_authorization_code,
    generate_code_challenge,
    generate_code_verifier,
    generate_state,
    get_workos_base_url,
    get_workos_client_id,
    poll_device_flow,
    refresh_access_token,
    start_device_flow,
)

WORKOS_URL = "https://api.workos.com"
TEST_CLIENT_ID = "client_test_123"


@pytest.fixture(autouse=True)
def mock_workos_env(monkeypatch):
    """Set WorkOS env vars for all tests."""
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", TEST_CLIENT_ID)
    monkeypatch.setenv("BOOKSHELF_WORKOS_BASE_URL", WORKOS_URL)


class TestPKCEUtilities:
    """Tests for PKCE helper functions."""

    def test_code_verifier_length(self):
        """Verifier should be a non-empty URL-safe string."""
        verifier = generate_code_verifier()
        assert len(verifier) >= 43

    def test_code_verifier_uniqueness(self):
        """Each call should produce a unique verifier."""
        v1 = generate_code_verifier()
        v2 = generate_code_verifier()
        assert v1 != v2

    def test_code_challenge_deterministic(self):
        """Same verifier should produce same challenge."""
        verifier = "test_verifier_value"
        c1 = generate_code_challenge(verifier)
        c2 = generate_code_challenge(verifier)
        assert c1 == c2

    def test_code_challenge_s256(self):
        """Challenge should be SHA-256 hash of verifier, base64url-encoded."""
        verifier = "test_verifier_value"
        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        assert generate_code_challenge(verifier) == expected

    def test_generate_state_uniqueness(self):
        """Each state should be unique."""
        s1 = generate_state()
        s2 = generate_state()
        assert s1 != s2

    def test_generate_state_non_empty(self):
        """State should be a non-empty string."""
        state = generate_state()
        assert len(state) > 0


class TestWorkOSConfig:
    """Tests for WorkOS configuration helpers."""

    def test_client_id_from_env(self, monkeypatch):
        """Should use BOOKSHELF_WORKOS_CLIENT_ID env var."""
        monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "env_client_id")
        assert get_workos_client_id() == "env_client_id"

    def test_client_id_staging_default(self, monkeypatch):
        """Should select staging client ID when API URL contains 'staging'."""
        monkeypatch.delenv("BOOKSHELF_WORKOS_CLIENT_ID", raising=False)
        result = get_workos_client_id("https://api.staging.example.com/bookshelf/v1")
        assert result == "client_01KABZE0E62YS9H7BMV6YZGMD1"

    def test_client_id_production_default(self, monkeypatch):
        """Should select production client ID for non-staging URLs."""
        monkeypatch.delenv("BOOKSHELF_WORKOS_CLIENT_ID", raising=False)
        result = get_workos_client_id("https://api.example.com/bookshelf/v1")
        assert result == "TODO_PRODUCTION_CLIENT_ID"

    def test_workos_base_url_from_env(self, monkeypatch):
        """Should use BOOKSHELF_WORKOS_BASE_URL env var."""
        monkeypatch.setenv("BOOKSHELF_WORKOS_BASE_URL", "https://custom.workos.com")
        assert get_workos_base_url() == "https://custom.workos.com"

    def test_workos_base_url_default(self, monkeypatch):
        """Should default to https://api.workos.com."""
        monkeypatch.delenv("BOOKSHELF_WORKOS_BASE_URL", raising=False)
        assert get_workos_base_url() == "https://api.workos.com"


class TestExchangeAuthorizationCode:
    """Tests for the authorization code exchange."""

    @respx.mock
    def test_exchange_success(self):
        """Should exchange code for tokens successfully."""
        token_response = {
            "access_token": "access_123",
            "refresh_token": "refresh_456",
            "expires_in": 3600,
        }
        respx.post(f"{WORKOS_URL}/user_management/authenticate").mock(
            return_value=httpx.Response(200, json=token_response)
        )

        result = _exchange_authorization_code(
            code="auth_code_789",
            code_verifier="verifier_abc",
            client_id=TEST_CLIENT_ID,
            redirect_uri="http://localhost:8400/callback",
            workos_url=WORKOS_URL,
        )

        assert result["access_token"] == "access_123"
        assert result["refresh_token"] == "refresh_456"
        assert result["expires_in"] == 3600

    @respx.mock
    def test_exchange_failure(self):
        """Should raise OAuthError on failed exchange."""
        respx.post(f"{WORKOS_URL}/user_management/authenticate").mock(
            return_value=httpx.Response(400, json={"message": "Invalid code"})
        )

        with pytest.raises(OAuthError, match="Token exchange failed"):
            _exchange_authorization_code(
                code="bad_code",
                code_verifier="verifier",
                client_id=TEST_CLIENT_ID,
                redirect_uri="http://localhost:8400/callback",
                workos_url=WORKOS_URL,
            )


class TestDeviceCodeFlow:
    """Tests for device code flow."""

    @respx.mock
    def test_start_device_flow_success(self):
        """Should start device flow and return DeviceFlowInfo."""
        device_response = {
            "user_code": "ABCD-1234",
            "verification_uri": "https://auth.workos.com/activate",
            "verification_uri_complete": "https://auth.workos.com/activate?user_code=ABCD-1234",
            "device_code": "device_code_xyz",
            "interval": 5,
            "expires_in": 600,
        }
        respx.post(f"{WORKOS_URL}/user_management/authorize/device").mock(
            return_value=httpx.Response(200, json=device_response)
        )

        result = start_device_flow(api_url="https://staging.example.com")

        assert isinstance(result, DeviceFlowInfo)
        assert result.user_code == "ABCD-1234"
        assert result.device_code == "device_code_xyz"
        assert result.interval == 5
        assert result.expires_in == 600

    @respx.mock
    def test_start_device_flow_failure(self):
        """Should raise OAuthError on failure."""
        respx.post(f"{WORKOS_URL}/user_management/authorize/device").mock(
            return_value=httpx.Response(400, json={"message": "Client not found"})
        )

        with pytest.raises(OAuthError, match="Failed to start device flow"):
            start_device_flow()

    @respx.mock
    def test_poll_pending_then_success(self):
        """Should poll until authorization completes."""
        token_response = {
            "access_token": "access_123",
            "refresh_token": "refresh_456",
            "expires_in": 3600,
        }

        # First call: pending, second call: success
        route = respx.post(f"{WORKOS_URL}/user_management/authenticate").mock(
            side_effect=[
                httpx.Response(400, json={"error": "authorization_pending"}),
                httpx.Response(200, json=token_response),
            ]
        )

        device_flow = DeviceFlowInfo(
            user_code="ABCD",
            verification_uri="https://example.com",
            verification_uri_complete="https://example.com?code=ABCD",
            device_code="dc_123",
            interval=0,  # No delay for tests
            expires_in=30,
        )

        with patch("bookshelf.oauth.time.sleep"):
            result = poll_device_flow(device_flow, timeout=30)

        assert result["access_token"] == "access_123"
        assert route.call_count == 2

    @respx.mock
    def test_poll_slow_down(self):
        """Should increase interval on slow_down response."""
        token_response = {
            "access_token": "access_123",
            "refresh_token": "refresh_456",
            "expires_in": 3600,
        }

        respx.post(f"{WORKOS_URL}/user_management/authenticate").mock(
            side_effect=[
                httpx.Response(400, json={"error": "slow_down"}),
                httpx.Response(200, json=token_response),
            ]
        )

        device_flow = DeviceFlowInfo(
            user_code="ABCD",
            verification_uri="https://example.com",
            verification_uri_complete="https://example.com?code=ABCD",
            device_code="dc_123",
            interval=0,
            expires_in=30,
        )

        sleep_calls = []

        with patch("bookshelf.oauth.time.sleep", side_effect=sleep_calls.append):
            result = poll_device_flow(device_flow, timeout=30)

        assert result["access_token"] == "access_123"
        # After slow_down, interval increases by 5
        assert any(s >= 5 for s in sleep_calls)

    @respx.mock
    def test_poll_expired(self):
        """Should raise OAuthError when device code expires."""
        respx.post(f"{WORKOS_URL}/user_management/authenticate").mock(
            return_value=httpx.Response(400, json={"error": "expired_token"})
        )

        device_flow = DeviceFlowInfo(
            user_code="ABCD",
            verification_uri="https://example.com",
            verification_uri_complete="https://example.com?code=ABCD",
            device_code="dc_123",
            interval=0,
            expires_in=30,
        )

        with patch("bookshelf.oauth.time.sleep"):
            with pytest.raises(OAuthError, match="expired"):
                poll_device_flow(device_flow, timeout=30)

    @respx.mock
    def test_poll_denied(self):
        """Should raise OAuthError when user denies authorization."""
        respx.post(f"{WORKOS_URL}/user_management/authenticate").mock(
            return_value=httpx.Response(400, json={"error": "access_denied"})
        )

        device_flow = DeviceFlowInfo(
            user_code="ABCD",
            verification_uri="https://example.com",
            verification_uri_complete="https://example.com?code=ABCD",
            device_code="dc_123",
            interval=0,
            expires_in=30,
        )

        with patch("bookshelf.oauth.time.sleep"):
            with pytest.raises(OAuthError, match="denied"):
                poll_device_flow(device_flow, timeout=30)

    def test_poll_timeout(self):
        """Should raise OAuthError on timeout."""
        device_flow = DeviceFlowInfo(
            user_code="ABCD",
            verification_uri="https://example.com",
            verification_uri_complete="https://example.com?code=ABCD",
            device_code="dc_123",
            interval=0,
            expires_in=0,  # Already expired
        )

        with patch("bookshelf.oauth.time.sleep"):
            with pytest.raises(OAuthError, match="Timed out"):
                poll_device_flow(device_flow, timeout=0)


class TestRefreshAccessToken:
    """Tests for token refresh."""

    @respx.mock
    def test_refresh_success(self):
        """Should refresh token successfully."""
        token_response = {
            "access_token": "new_access_123",
            "refresh_token": "new_refresh_456",
            "expires_in": 3600,
        }
        route = respx.post(f"{WORKOS_URL}/user_management/authenticate").mock(
            return_value=httpx.Response(200, json=token_response)
        )

        result = refresh_access_token("old_refresh_token")

        assert result["access_token"] == "new_access_123"
        assert result["refresh_token"] == "new_refresh_456"
        assert route.called

    @respx.mock
    def test_refresh_failure(self):
        """Should raise OAuthError on failure."""
        respx.post(f"{WORKOS_URL}/user_management/authenticate").mock(
            return_value=httpx.Response(400, json={"message": "Invalid refresh token"})
        )

        with pytest.raises(OAuthError, match="Token refresh failed"):
            refresh_access_token("bad_refresh_token")

    @respx.mock
    def test_refresh_sends_correct_payload(self):
        """Should send correct grant_type and parameters."""
        route = respx.post(f"{WORKOS_URL}/user_management/authenticate").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "new_token",
                    "refresh_token": "new_refresh",
                    "expires_in": 3600,
                },
            )
        )

        refresh_access_token("my_refresh_token")

        request = route.calls.last.request
        body = json.loads(request.content)
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "my_refresh_token"
        assert body["client_id"] == TEST_CLIENT_ID
