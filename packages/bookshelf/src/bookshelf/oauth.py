"""OAuth authentication flows for WorkOS integration.

Supports Authorization Code + PKCE (desktop) and Device Code (headless) flows.
"""

import base64
import hashlib
import os
import secrets
import socket
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event, Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

# Default WorkOS client IDs (public - safe to hardcode for PKCE apps)
_CLIENT_IDS = {
    "staging": "client_01KABZE0E62YS9H7BMV6YZGMD1",
    "production": "TODO_PRODUCTION_CLIENT_ID",
}

_DEFAULT_WORKOS_BASE_URL = "https://api.workos.com"

# Port range for local callback server
_CALLBACK_PORT_MIN = 8400
_CALLBACK_PORT_MAX = 8409

# Timeouts
_AUTH_CODE_TIMEOUT = 120  # seconds to wait for browser redirect
_DEVICE_CODE_TIMEOUT = 300  # seconds to wait for device code approval


class OAuthError(Exception):
    """Error during OAuth authentication flow."""


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def get_workos_client_id(api_url: str = "") -> str:
    """Get WorkOS client ID from env var or default based on API URL.

    Parameters
    ----------
    api_url
        The bookshelf API URL, used to select staging vs production client ID.

    Returns
    -------
    str
        WorkOS client ID
    """
    env_id = os.environ.get("BOOKSHELF_WORKOS_CLIENT_ID")
    if env_id:
        return env_id

    if "staging" in api_url:
        return _CLIENT_IDS["staging"]
    return _CLIENT_IDS["production"]


def get_workos_base_url() -> str:
    """Get WorkOS base URL from env var or default.

    Returns
    -------
    str
        WorkOS API base URL
    """
    return os.environ.get("BOOKSHELF_WORKOS_BASE_URL", _DEFAULT_WORKOS_BASE_URL)


# ---------------------------------------------------------------------------
# PKCE utilities
# ---------------------------------------------------------------------------


def generate_code_verifier() -> str:
    """Generate a cryptographic random code verifier for PKCE.

    Returns
    -------
    str
        URL-safe random string (43-128 chars per RFC 7636)
    """
    return secrets.token_urlsafe(32)


def generate_code_challenge(verifier: str) -> str:
    """Generate S256 code challenge from a code verifier.

    Parameters
    ----------
    verifier
        The code verifier string

    Returns
    -------
    str
        Base64url-encoded SHA-256 hash of the verifier
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_state() -> str:
    """Generate a random state parameter for CSRF protection.

    Returns
    -------
    str
        URL-safe random string
    """
    return secrets.token_urlsafe(16)


# ---------------------------------------------------------------------------
# Authorization Code + PKCE flow
# ---------------------------------------------------------------------------


def _find_available_port() -> int:
    """Find an available port in the callback port range.

    Returns
    -------
    int
        Available port number

    Raises
    ------
    OAuthError
        If no ports are available
    """
    for port in range(_CALLBACK_PORT_MIN, _CALLBACK_PORT_MAX + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise OAuthError(
        f"No available ports in range {_CALLBACK_PORT_MIN}-{_CALLBACK_PORT_MAX}. "
        "Try using --device-code instead."
    )


def authorization_code_flow(
    api_url: str = "",
    timeout: int = _AUTH_CODE_TIMEOUT,
) -> dict[str, Any]:
    """Run Authorization Code + PKCE flow via browser redirect.

    Opens the user's browser to the WorkOS authorization page.
    A local HTTP server captures the callback with the authorization code,
    then exchanges it for tokens.

    Parameters
    ----------
    api_url
        Bookshelf API URL (used to select client ID)
    timeout
        Seconds to wait for the browser redirect

    Returns
    -------
    dict
        Token response with ``access_token``, ``refresh_token``, ``expires_in``

    Raises
    ------
    OAuthError
        On any failure (timeout, state mismatch, exchange error)
    """
    client_id = get_workos_client_id(api_url)
    workos_url = get_workos_base_url()

    # PKCE parameters
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = generate_state()

    # Find a port and set up redirect URI
    port = _find_available_port()
    redirect_uri = f"http://localhost:{port}/callback"

    # State shared with callback handler
    result: dict[str, str | None] = {"code": None, "error": None, "state": None}
    received = Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            params = parse_qs(urlparse(self.path).query)
            result["code"] = params.get("code", [None])[0]
            result["error"] = params.get("error", [None])[0]
            result["state"] = params.get("state", [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authentication successful!</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
            received.set()

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Suppress HTTP server logs

    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    server_thread = Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    # Build authorization URL
    auth_params = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "provider": "authkit",
        }
    )
    auth_url = f"{workos_url}/user_management/authorize?{auth_params}"

    # Open browser
    browser_opened = webbrowser.open(auth_url)
    if not browser_opened:
        server.server_close()
        raise OAuthError(
            f"Could not open browser. Visit this URL manually:\n{auth_url}\n\n"
            "Or use --device-code for headless authentication."
        )

    # Wait for callback
    if not received.wait(timeout=timeout):
        server.server_close()
        raise OAuthError("Timed out waiting for browser authentication. " "Try again or use --device-code.")
    server.server_close()

    # Check for errors
    if result["error"]:
        raise OAuthError(f"Authorization failed: {result['error']}")

    if not result["code"]:
        raise OAuthError("No authorization code received from callback.")

    # CSRF check
    if result["state"] != state:
        raise OAuthError("State parameter mismatch - possible CSRF attack.")

    # Exchange code for tokens
    return _exchange_authorization_code(
        code=result["code"],
        code_verifier=code_verifier,
        client_id=client_id,
        redirect_uri=redirect_uri,
        workos_url=workos_url,
    )


def _exchange_authorization_code(
    code: str,
    code_verifier: str,
    client_id: str,
    redirect_uri: str,
    workos_url: str,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens.

    Parameters
    ----------
    code
        Authorization code from the callback
    code_verifier
        PKCE code verifier
    client_id
        WorkOS client ID
    redirect_uri
        The redirect URI used in the authorization request
    workos_url
        WorkOS base URL

    Returns
    -------
    dict
        Token response

    Raises
    ------
    OAuthError
        If the token exchange fails
    """
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{workos_url}/user_management/authenticate",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
            },
        )

    if not response.is_success:
        try:
            detail = response.json().get("message", response.text)
        except Exception:
            detail = response.text
        raise OAuthError(f"Token exchange failed: {detail}")

    token_data: dict[str, Any] = response.json()
    return token_data


# ---------------------------------------------------------------------------
# Device Code flow
# ---------------------------------------------------------------------------


@dataclass
class DeviceFlowInfo:
    """Information returned when starting a device code flow."""

    user_code: str
    verification_uri: str
    verification_uri_complete: str
    device_code: str
    interval: int
    expires_in: int


def start_device_flow(api_url: str = "") -> DeviceFlowInfo:
    """Start a device code authorization flow.

    Parameters
    ----------
    api_url
        Bookshelf API URL (used to select client ID)

    Returns
    -------
    DeviceFlowInfo
        Device flow details including user code and verification URI

    Raises
    ------
    OAuthError
        If the device flow initiation fails
    """
    client_id = get_workos_client_id(api_url)
    workos_url = get_workos_base_url()

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{workos_url}/user_management/authorize/device",
            json={"client_id": client_id},
        )

    if not response.is_success:
        try:
            detail = response.json().get("message", response.text)
        except Exception:
            detail = response.text
        raise OAuthError(f"Failed to start device flow: {detail}")

    data = response.json()
    return DeviceFlowInfo(
        user_code=data["user_code"],
        verification_uri=data["verification_uri"],
        verification_uri_complete=data.get("verification_uri_complete", data["verification_uri"]),
        device_code=data["device_code"],
        interval=data.get("interval", 5),
        expires_in=data.get("expires_in", _DEVICE_CODE_TIMEOUT),
    )


def poll_device_flow(
    device_flow: DeviceFlowInfo,
    api_url: str = "",
    timeout: int | None = None,
) -> dict[str, Any]:
    """Poll for device code authorization completion.

    Parameters
    ----------
    device_flow
        Device flow info from ``start_device_flow()``
    api_url
        Bookshelf API URL (used to select client ID)
    timeout
        Maximum seconds to poll (defaults to device_flow.expires_in)

    Returns
    -------
    dict
        Token response with ``access_token``, ``refresh_token``, ``expires_in``

    Raises
    ------
    OAuthError
        On timeout, denied, or expired device code
    """
    client_id = get_workos_client_id(api_url)
    workos_url = get_workos_base_url()
    interval = device_flow.interval
    max_time = timeout if timeout is not None else device_flow.expires_in
    deadline = time.monotonic() + max_time

    with httpx.Client(timeout=30.0) as client:
        while time.monotonic() < deadline:
            time.sleep(interval)

            response = client.post(
                f"{workos_url}/user_management/authenticate",
                json={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_flow.device_code,
                    "client_id": client_id,
                },
            )

            if response.is_success:
                token_data: dict[str, Any] = response.json()
                return token_data

            try:
                error_data = response.json()
                error_code = error_data.get("error", error_data.get("code", ""))
            except Exception:
                raise OAuthError(f"Unexpected response: {response.text}")

            if error_code == "authorization_pending":
                continue
            elif error_code == "slow_down":
                interval += 5
                continue
            elif error_code in ("expired_token", "expired"):
                raise OAuthError("Device code expired. Please try again.")
            elif error_code in ("access_denied", "denied"):
                raise OAuthError("Authorization was denied by the user.")
            else:
                detail = error_data.get("message", error_data.get("error_description", error_code))
                raise OAuthError(f"Device authorization failed: {detail}")

    raise OAuthError("Timed out waiting for device authorization.")


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


def refresh_access_token(
    refresh_token: str,
    api_url: str = "",
) -> dict[str, Any]:
    """Refresh an access token using a refresh token.

    WorkOS rotates refresh tokens on each use, so the caller must
    save the new refresh_token from the response.

    Parameters
    ----------
    refresh_token
        The refresh token to use
    api_url
        Bookshelf API URL (used to select client ID)

    Returns
    -------
    dict
        Token response with new ``access_token``, ``refresh_token``, ``expires_in``

    Raises
    ------
    OAuthError
        If the refresh fails (e.g., token revoked or expired)
    """
    client_id = get_workos_client_id(api_url)
    workos_url = get_workos_base_url()

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{workos_url}/user_management/authenticate",
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
        )

    if not response.is_success:
        try:
            detail = response.json().get("message", response.text)
        except Exception:
            detail = response.text
        raise OAuthError(f"Token refresh failed: {detail}")

    token_data: dict[str, Any] = response.json()
    return token_data
