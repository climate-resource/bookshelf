"""WorkOS OAuth flows for interactive login.

Supports Authorization Code + PKCE (browser, RFC 7636) and Device Authorization (headless, RFC 8628).
This is the only interactive credential acquisition in the SDK.
:mod:`bookshelf._core.credentials` stores what these flows return,
and :mod:`bookshelf._core.auth` refreshes it.
"""

import base64
import hashlib
import os
import secrets
import socket
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event, Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

# Public WorkOS client IDs (safe to hardcode for PKCE/device-code apps).
# Production ID is not bundled — it must be supplied via BOOKSHELF_WORKOS_CLIENT_ID.
_CLIENT_IDS: dict[str, str | None] = {
    "staging": "client_01KABZE0E62YS9H7BMV6YZGMD1",
    "production": None,
}

# Tokens carry the issuer of the domain that minted them,
# and the backends pin the custom-domain issuer,
# so minting through api.workos.com would fail issuer verification.
_DEFAULT_WORKOS_BASE_URL = "https://auth-api.climateresource.com.au"

# Loopback callback server port range for the PKCE flow.
_CALLBACK_PORT_MIN = 8400
_CALLBACK_PORT_MAX = 8409

_AUTH_CODE_TIMEOUT = 120  # seconds to wait for the browser redirect
_DEVICE_CODE_TIMEOUT = 300  # seconds to wait for device-code approval


# Self-contained HTML for the loopback callback page shown after the browser redirect.
# No external assets — the page must render offline.
def _render_callback_page(*, success: bool, detail: str = "") -> bytes:
    accent = "#28c9c4" if success else "#f69f18"
    glyph = "&#10003;" if success else "&#33;"  # check / bang
    eyebrow = "CLI AUTHENTICATION"
    if success:
        heading = "Authentication successful"
        body = "You&rsquo;re signed in. Close this tab and return to your terminal."
    else:
        heading = "Authentication failed"
        body = detail or "Something went wrong. Return to your terminal and try again."
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading} &middot; Bookshelf</title>
<style>
  :root {{
    --ink: #011f26; --muted: #67868d; --canvas: #f5f5f5; --card: #ffffff;
    --line: #e5e5e5; --teal: #28c9c4; --accent: {accent};
    --font-sans: "Geist Variable", "Geist", system-ui, -apple-system, sans-serif;
    --font-serif: "Brawler", Georgia, "Times New Roman", serif;
    --font-mono: "Geist Mono Variable", "Geist Mono", "Fira Code", Consolas, monospace;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --ink: #e6ebec; --muted: #67868d; --canvas: #011f26; --card: #013541;
      --line: #345d67; --teal: #58e9e4;
    }}
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ height: 100%; margin: 0; }}
  body {{
    display: grid; place-items: center; padding: 24px;
    background-color: var(--canvas);
    background-image:
      linear-gradient(var(--line) 1px, transparent 1px),
      linear-gradient(90deg, var(--line) 1px, transparent 1px);
    background-size: 32px 32px;
    color: var(--ink);
    font-family: var(--font-sans);
    -webkit-font-smoothing: antialiased;
  }}
  .card {{
    width: 100%; max-width: 500px; background: var(--card);
    border: 1px solid var(--line); border-top: 2px solid var(--teal);
    box-shadow: 0 1px 0 var(--line);
    padding: 38px 36px 28px;
  }}
  .eyebrow {{
    font-family: var(--font-mono);
    font-size: 11px; letter-spacing: 0.16em; color: var(--muted);
    margin: 0 0 24px; text-transform: uppercase;
  }}
  .mark {{
    width: 44px; height: 44px; display: grid; place-items: center;
    background: var(--accent); color: var(--card);
    font-size: 24px; line-height: 1; margin-bottom: 20px;
  }}
  h1 {{ font-family: var(--font-sans); font-size: 30px; font-weight: 700; margin: 0 0 10px; }}
  p {{ font-size: 15px; line-height: 1.55; color: var(--muted); margin: 0; }}
  .rule {{ height: 1px; background: var(--line); margin: 28px 0 14px; }}
  .foot {{
    font-family: var(--font-mono);
    font-size: 11px; letter-spacing: 0.04em; color: var(--muted);
    display: flex; justify-content: space-between;
  }}
  .foot .dot {{ color: var(--teal); }}
  .foot a {{
    color: var(--teal); text-decoration: underline; text-underline-offset: 2px;
  }}
</style>
</head>
<body>
  <main class="card">
    <p class="eyebrow">{eyebrow}</p>
    <div class="mark" aria-hidden="true">{glyph}</div>
    <h1>{heading}</h1>
    <p>{body}</p>
    <div class="rule"></div>
    <div class="foot">
      <span>bookshelf&nbsp;cli</span>
      <span><span class="dot">&bull;</span>&nbsp;<a href="https://climate-resource.com" target="_blank" rel="noopener noreferrer">climate&nbsp;resource</a></span>
    </div>
  </main>
</body>
</html>""".encode()


class OAuthError(Exception):
    """Error during an OAuth authentication flow."""


def get_workos_client_id(api_url: str = "") -> str:
    """Return the WorkOS client ID from ``$BOOKSHELF_WORKOS_CLIENT_ID`` or pick one by API URL.

    The staging client ID is bundled.
    The production client ID is not bundled and must be supplied via the environment variable;
    omitting it on a non-staging URL raises ``OAuthError`` with an actionable message.
    """
    env_id = os.environ.get("BOOKSHELF_WORKOS_CLIENT_ID")
    if env_id:
        return env_id
    if "staging" in api_url:
        return _CLIENT_IDS["staging"]  # type: ignore[return-value]
    raise OAuthError(
        "Production login requires setting the BOOKSHELF_WORKOS_CLIENT_ID environment variable. "
        "The production WorkOS client ID is not bundled in the SDK. "
        "Set BOOKSHELF_WORKOS_CLIENT_ID to your WorkOS client ID and retry."
    )


def get_workos_base_url() -> str:
    """Return the WorkOS base URL from ``$BOOKSHELF_WORKOS_BASE_URL`` or the default."""
    return os.environ.get("BOOKSHELF_WORKOS_BASE_URL", _DEFAULT_WORKOS_BASE_URL)


def generate_code_verifier() -> str:
    """Return a cryptographically random PKCE code verifier (RFC 7636)."""
    return secrets.token_urlsafe(32)


def generate_code_challenge(verifier: str) -> str:
    """Return the S256 code challenge for ``verifier`` (base64url SHA-256, unpadded)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_state() -> str:
    """Return a random ``state`` parameter for CSRF protection."""
    return secrets.token_urlsafe(16)


def _find_available_port() -> int:
    """Bind-probe the callback port range and return the first free port."""
    for port in range(_CALLBACK_PORT_MIN, _CALLBACK_PORT_MAX + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise OAuthError(
        f"No available ports in range {_CALLBACK_PORT_MIN}-{_CALLBACK_PORT_MAX}. "
        "Try --device-code instead."
    )


def authorization_code_flow(
    api_url: str = "",
    *,
    timeout: float = _AUTH_CODE_TIMEOUT,
    on_auth_url: Callable[[str], None] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Run the Authorization Code + PKCE flow via a browser redirect.

    Opens the user's browser at the WorkOS authorization page
    and captures the redirect on a loopback HTTP server,
    then exchanges the authorization code for tokens.

    Parameters
    ----------
    api_url
        Bookshelf API URL, used to select the WorkOS client ID.
    timeout
        Seconds to wait for the browser redirect.
    on_auth_url
        Callback invoked with the authorization URL
        so callers can show it when the browser does not open.
    transport
        Optional httpx transport override (used in tests).

    Returns
    -------
    dict
        Token response with ``access_token``, ``refresh_token``, ``expires_in``.
    """
    client_id = get_workos_client_id(api_url)
    workos_url = get_workos_base_url()

    code_verifier = generate_code_verifier()
    state = generate_state()

    port = _find_available_port()
    redirect_uri = f"http://localhost:{port}/callback"

    result: dict[str, str | None] = {"code": None, "error": None, "state": None}
    received = Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            params = parse_qs(urlparse(self.path).query)
            result["code"] = params.get("code", [None])[0]
            result["error"] = params.get("error", [None])[0]
            result["state"] = params.get("state", [None])[0]
            ok = result["error"] is None and result["code"] is not None
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_render_callback_page(success=ok, detail=result["error"] or ""))
            received.set()

        def log_message(self, *args: Any) -> None:
            """Suppress HTTP server logging."""

    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    server_thread = Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    auth_params = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": generate_code_challenge(code_verifier),
            "code_challenge_method": "S256",
            "state": state,
            "provider": "authkit",
        }
    )
    auth_url = f"{workos_url}/user_management/authorize?{auth_params}"

    if on_auth_url is not None:
        on_auth_url(auth_url)
    webbrowser.open(auth_url)

    try:
        if not received.wait(timeout=timeout):
            raise OAuthError(
                "Timed out waiting for browser authentication. Try again or use --device-code."
            )
    finally:
        server.server_close()

    if result["error"]:
        raise OAuthError(f"Authorization failed: {result['error']}")
    if not result["code"]:
        raise OAuthError("No authorization code received from callback.")
    if result["state"] != state:
        raise OAuthError("State parameter mismatch - possible CSRF attack.")

    return _exchange_authorization_code(
        code=result["code"],
        code_verifier=code_verifier,
        client_id=client_id,
        redirect_uri=redirect_uri,
        workos_url=workos_url,
        transport=transport,
    )


def _exchange_authorization_code(
    *,
    code: str,
    code_verifier: str,
    client_id: str,
    redirect_uri: str,
    workos_url: str,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens, raising ``OAuthError`` on failure."""
    with httpx.Client(timeout=30.0, transport=transport) as client:
        response = client.post(
            f"{workos_url}/user_management/authenticate",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
            },
        )
    if not response.is_success:
        raise OAuthError(f"Token exchange failed: {_error_detail(response)}")
    token_data: dict[str, Any] = response.json()
    return token_data


@dataclass
class DeviceFlowInfo:
    """Details returned when starting a device-code flow."""

    user_code: str
    verification_uri: str
    verification_uri_complete: str
    device_code: str
    interval: int
    expires_in: int


def start_device_flow(
    api_url: str = "",
    *,
    transport: httpx.BaseTransport | None = None,
) -> DeviceFlowInfo:
    """Start a device authorization flow and return the user code + verification URI."""
    client_id = get_workos_client_id(api_url)
    workos_url = get_workos_base_url()

    with httpx.Client(timeout=30.0, transport=transport) as client:
        response = client.post(
            f"{workos_url}/user_management/authorize/device",
            data={"client_id": client_id},
        )
    if not response.is_success:
        raise OAuthError(f"Failed to start device flow: {_error_detail(response)}")

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
    *,
    timeout: float | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Poll until the device code is approved and return the token response.

    Honors ``authorization_pending`` and ``slow_down`` per RFC 8628.
    Raises ``OAuthError`` on denial, expiry, or timeout.
    """
    client_id = get_workos_client_id(api_url)
    workos_url = get_workos_base_url()
    interval = device_flow.interval
    max_time = timeout if timeout is not None else device_flow.expires_in
    deadline = time.monotonic() + max_time

    with httpx.Client(timeout=30.0, transport=transport) as client:
        while time.monotonic() <= deadline:
            time.sleep(interval)

            response = client.post(
                f"{workos_url}/user_management/authenticate",
                data={
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
            except ValueError as exc:
                raise OAuthError(f"Unexpected response: {response.text}") from exc
            error_code = error_data.get("error", error_data.get("code", ""))

            if error_code == "authorization_pending":
                continue
            if error_code == "slow_down":
                interval += 5
                continue
            if error_code in ("expired_token", "expired"):
                raise OAuthError("Device code expired. Please try again.")
            if error_code in ("access_denied", "denied"):
                raise OAuthError("Authorization was denied by the user.")
            detail = error_data.get("message", error_data.get("error_description", error_code))
            raise OAuthError(f"Device authorization failed: {detail}")

    raise OAuthError("Timed out waiting for device authorization.")


def refresh_access_token(
    refresh_token: str,
    api_url: str = "",
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Refresh an access token using a refresh token.

    WorkOS rotates refresh tokens on each use,
    so callers must persist the new ``refresh_token`` from the response.
    """
    client_id = get_workos_client_id(api_url)
    workos_url = get_workos_base_url()

    with httpx.Client(timeout=30.0, transport=transport) as client:
        response = client.post(
            f"{workos_url}/user_management/authenticate",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
        )
    if not response.is_success:
        raise OAuthError(f"Token refresh failed: {_error_detail(response)}")
    token_data: dict[str, Any] = response.json()
    return token_data


def _error_detail(response: httpx.Response) -> str:
    """Extract a human-readable error detail from a failed WorkOS response."""
    try:
        detail = response.json().get("message", response.text)
    except ValueError:
        detail = response.text
    return str(detail)


__all__ = [
    "DeviceFlowInfo",
    "OAuthError",
    "authorization_code_flow",
    "poll_device_flow",
    "refresh_access_token",
    "start_device_flow",
]
