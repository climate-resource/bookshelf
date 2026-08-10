"""Tests for the WorkOS OAuth flows (``bookshelf._core.oauth``)."""

from urllib.parse import parse_qsl, urlparse

import httpx
import pytest

from bookshelf._core import oauth as _oauth


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture poll sleeps instead of actually sleeping.

    Also sets a test-scoped BOOKSHELF_WORKOS_CLIENT_ID.
    Flows called without an explicit staging URL
    therefore do not hit the fail-loud production guard.
    """
    sleeps: list[float] = []
    monkeypatch.setattr(_oauth.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client_test")
    return sleeps


def _flow(interval: int = 0, expires_in: int = 300) -> _oauth.DeviceFlowInfo:
    return _oauth.DeviceFlowInfo(
        user_code="WDJB-MJHT",
        verification_uri="https://auth.test/device",
        verification_uri_complete="https://auth.test/device?user_code=WDJB-MJHT",
        device_code="dev-1",
        interval=interval,
        expires_in=expires_in,
    )


def test_code_challenge_matches_rfc7636_vector() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert _oauth.generate_code_challenge(verifier) == expected


def test_code_verifier_length_within_rfc_bounds() -> None:
    assert 43 <= len(_oauth.generate_code_verifier()) <= 128


def test_client_id_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOKSHELF_WORKOS_CLIENT_ID", raising=False)
    staging_url = "https://api.staging.example/bookshelf/v1"
    assert _oauth.require_workos_client_id(staging_url) == _oauth._CLIENT_IDS["staging"]
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client_custom")
    assert _oauth.require_workos_client_id() == "client_custom"


def test_client_id_production_no_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production login without BOOKSHELF_WORKOS_CLIENT_ID must raise OAuthError."""
    monkeypatch.delenv("BOOKSHELF_WORKOS_CLIENT_ID", raising=False)
    production_url = "https://api.bookshelf.example/v1"
    with pytest.raises(_oauth.OAuthError, match="BOOKSHELF_WORKOS_CLIENT_ID"):
        _oauth.require_workos_client_id(production_url)


def test_unresolvable_client_id_is_none_for_the_ambient_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One resolver, two failure shapes: a login raises, ambient resolution decides for itself."""
    monkeypatch.delenv("BOOKSHELF_WORKOS_CLIENT_ID", raising=False)
    assert _oauth.resolve_workos_client_id("https://api.bookshelf.example/v1") is None


def test_client_id_production_with_env_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting BOOKSHELF_WORKOS_CLIENT_ID must satisfy production login."""
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client_prod_custom")
    production_url = "https://api.bookshelf.example/v1"
    assert _oauth.require_workos_client_id(production_url) == "client_prod_custom"


def test_start_device_flow_parses_response() -> None:
    payload = {
        "device_code": "dev-1",
        "user_code": "WDJB-MJHT",
        "verification_uri": "https://auth.test/device",
        "verification_uri_complete": "https://auth.test/device?user_code=WDJB-MJHT",
        "expires_in": 300,
        "interval": 5,
    }
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    flow = _oauth.start_device_flow(transport=transport)
    assert flow.user_code == "WDJB-MJHT"
    assert flow.device_code == "dev-1"
    assert flow.interval == 5


def test_poll_device_flow_pending_then_success() -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(400, json={"error": "authorization_pending"})
        return httpx.Response(200, json={"access_token": "tok", "refresh_token": "ref"})

    tokens = _oauth.poll_device_flow(_flow(), transport=httpx.MockTransport(handler))
    assert tokens["access_token"] == "tok"
    assert calls["n"] == 3


def test_poll_device_flow_slow_down_backs_off(no_sleep: list[float]) -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(400, json={"error": "slow_down"})
        return httpx.Response(200, json={"access_token": "tok"})

    tokens = _oauth.poll_device_flow(_flow(), transport=httpx.MockTransport(handler))
    assert tokens["access_token"] == "tok"
    assert no_sleep == [0, 5]  # interval bumped by 5s after slow_down (RFC 8628)


@pytest.mark.parametrize(
    ("error", "match"),
    [("access_denied", "denied"), ("expired_token", "expired"), ("invalid_grant", "failed")],
)
def test_poll_device_flow_terminal_errors(error: str, match: str) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(400, json={"error": error}))
    with pytest.raises(_oauth.OAuthError, match=match):
        _oauth.poll_device_flow(_flow(), transport=transport)


def test_poll_device_flow_times_out() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(400, json={"error": "authorization_pending"})
    )
    with pytest.raises(_oauth.OAuthError, match="Timed out"):
        _oauth.poll_device_flow(_flow(), timeout=0, transport=transport)


def test_callback_page_escapes_provider_error() -> None:
    page = _oauth._render_callback_page(
        success=False,
        detail="<script>alert('xss')</script>",
    )

    assert b"<script>" not in page
    assert b"&lt;script&gt;" in page


def test_authorization_code_flow_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full PKCE loop: browser open -> loopback callback -> code exchange."""
    auth_request: dict[str, str] = {}
    shown: list[str] = []

    def fake_open(url: str) -> bool:
        params = dict(parse_qsl(urlparse(url).query))
        auth_request.update(params)
        # Simulate the user approving in the browser: WorkOS redirects to the loopback server.
        callback = f"{params['redirect_uri']}?code=auth-code-1&state={params['state']}"
        httpx.get(callback)
        return True

    monkeypatch.setattr(_oauth.webbrowser, "open", fake_open)

    def token_handler(request: httpx.Request) -> httpx.Response:
        body = dict(parse_qsl(request.content.decode()))
        assert body["grant_type"] == "authorization_code"
        assert body["code"] == "auth-code-1"
        # The verifier sent at exchange must hash to the challenge sent at authorization.
        challenge = _oauth.generate_code_challenge(body["code_verifier"])
        assert challenge == auth_request["code_challenge"]
        return httpx.Response(200, json={"access_token": "tok-pkce", "refresh_token": "ref"})

    tokens = _oauth.authorization_code_flow(
        on_auth_url=shown.append,
        transport=httpx.MockTransport(token_handler),
    )
    assert tokens["access_token"] == "tok-pkce"
    assert auth_request["code_challenge_method"] == "S256"
    assert auth_request["provider"] == "authkit"
    assert shown and shown[0].startswith("https://")


def test_authorization_code_flow_rejects_state_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_open(url: str) -> bool:
        params = dict(parse_qsl(urlparse(url).query))
        httpx.get(f"{params['redirect_uri']}?code=auth-code-1&state=tampered")
        return True

    monkeypatch.setattr(_oauth.webbrowser, "open", fake_open)
    with pytest.raises(_oauth.OAuthError, match="State parameter mismatch"):
        _oauth.authorization_code_flow()


def test_authorization_code_flow_surfaces_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_open(url: str) -> bool:
        params = dict(parse_qsl(urlparse(url).query))
        httpx.get(f"{params['redirect_uri']}?error=access_denied&state={params['state']}")
        return True

    monkeypatch.setattr(_oauth.webbrowser, "open", fake_open)
    with pytest.raises(_oauth.OAuthError, match="access_denied"):
        _oauth.authorization_code_flow()


def test_exchange_failure_raises() -> None:
    def fake_open(url: str) -> bool:
        params = dict(parse_qsl(urlparse(url).query))
        httpx.get(f"{params['redirect_uri']}?code=bad-code&state={params['state']}")
        return True

    transport = httpx.MockTransport(lambda _: httpx.Response(400, json={"message": "invalid code"}))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(_oauth.webbrowser, "open", fake_open)
        with pytest.raises(_oauth.OAuthError, match="invalid code"):
            _oauth.authorization_code_flow(transport=transport)


@pytest.mark.parametrize(
    "api_url",
    [
        "https://bookshelf-staging.ovh.climateresource.com.au",
        "https://api.staging.example/bookshelf/v1",
        "https://staging.test",
    ],
)
def test_staging_api_urls_are_recognised(api_url: str) -> None:
    assert _oauth.is_staging_api_url(api_url)


@pytest.mark.parametrize(
    "api_url",
    [
        "https://api.climateresource.com.au/bookshelf",
        # The word appears, but not as part of a host label.
        "https://api.climateresource.com.au/bookshelf/staging",
        "https://api.example/v1?note=staging",
        "https://mystaging.example",
    ],
)
def test_non_staging_api_urls_are_not_recognised(api_url: str) -> None:
    assert not _oauth.is_staging_api_url(api_url)


def test_client_id_ignores_a_staging_path_on_a_production_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path that spells the word must not pull a production login onto staging."""
    monkeypatch.delenv("BOOKSHELF_WORKOS_CLIENT_ID", raising=False)
    with pytest.raises(_oauth.OAuthError):
        _oauth.require_workos_client_id("https://api.climateresource.com.au/bookshelf/staging")
