"""Confirming a client's credential, and logging in when a person can."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from bookshelf import AsyncBookshelf, AuthenticationRequiredError, Bookshelf, BookshelfError
from bookshelf._core import credentials, session
from bookshelf._core.credentials import StoredCredentials
from bookshelf._core.errors import APIError
from bookshelf._generated import models
from tests import _core_payloads as payloads

BASE_URL = "https://bookshelf.test"
TOKEN_URL = "https://issuer.test/token"
USER = {"id": "user_1", "email": "someone@example.com", "organization_id": "org_1"}

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def isolated_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(credentials, "credentials_path", lambda: path)
    for name in (
        "BOOKSHELF_TOKEN",
        "BOOKSHELF_CLIENT_ID",
        "BOOKSHELF_CLIENT_SECRET",
        "BOOKSHELF_TOKEN_URL",
        "BOOKSHELF_USE_KEYCHAIN",
        "BOOKSHELF_URL",
        "CI",
        "SSH_CONNECTION",
        "SSH_TTY",
    ):
        monkeypatch.delenv(name, raising=False)


def _api(recorded: list[httpx.Request], *, accept: str | None) -> Handler:
    """Answer ``/auth/me`` for the bearer ``accept`` and 401 otherwise, and create any draft."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"access_token": "minted", "expires_in": 3600})
        if request.headers.get("Authorization") != f"Bearer {accept}":
            return httpx.Response(401, json={"detail": "unauthorised"})
        if request.url.path.endswith("/auth/me"):
            return httpx.Response(200, json=USER)
        return httpx.Response(201, json=payloads.BOOK_DETAIL)

    return handler


def _fake_login(calls: list[str]) -> Callable[..., tuple[models.UserResponse, StoredCredentials]]:
    def login(api_url: str, *, browser: bool) -> tuple[models.UserResponse, StoredCredentials]:
        calls.append(api_url)
        record = StoredCredentials(
            access_token="fresh",
            token_type="bearer",
            expires_at=None,
            api_url=api_url,
            refresh_token=None,
        )
        return models.UserResponse(**USER), record

    return login


def test_a_stored_login_is_confirmed_once() -> None:
    credentials.save_credentials("stored", api_url=BASE_URL)
    recorded: list[httpx.Request] = []

    with Bookshelf(BASE_URL, transport=httpx.MockTransport(_api(recorded, accept="stored"))) as bs:
        first = bs.ensure_authenticated(interactive=False)
        second = bs.ensure_authenticated(interactive=False)

    assert first.email == second.email == USER["email"]
    assert len(recorded) == 1


def test_ci_client_credentials_are_exchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_CLIENT_ID", "machine")
    monkeypatch.setenv("BOOKSHELF_CLIENT_SECRET", "secret")
    monkeypatch.setenv("BOOKSHELF_TOKEN_URL", TOKEN_URL)
    monkeypatch.setenv("CI", "true")
    recorded: list[httpx.Request] = []

    with Bookshelf(BASE_URL, transport=httpx.MockTransport(_api(recorded, accept="minted"))) as bs:
        user = bs.ensure_authenticated()

    assert user.id == USER["id"]
    assert [str(request.url) for request in recorded][0] == TOKEN_URL


def test_nobody_to_log_in_raises_with_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session, "login_user", _fake_login(calls := []))

    transport = httpx.MockTransport(_api([], accept=None))

    with (
        Bookshelf(BASE_URL, transport=transport) as bs,
        pytest.raises(AuthenticationRequiredError, match="bookshelf auth login"),
    ):
        bs.ensure_authenticated(interactive=False)

    assert calls == []


def test_ci_is_never_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")

    assert not session.is_interactive()


def test_a_person_is_logged_in_and_the_client_uses_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session, "is_interactive", lambda: True)
    monkeypatch.setattr(session, "login_user", _fake_login(calls := []))
    recorded: list[httpx.Request] = []

    with Bookshelf(BASE_URL, transport=httpx.MockTransport(_api(recorded, accept="fresh"))) as bs:
        bs.draft_book("primap-hist", version="1.0.0")

    assert calls == [BASE_URL]
    assert recorded[-1].method == "POST"
    assert recorded[-1].headers["Authorization"] == "Bearer fresh"


def test_a_spent_stored_login_is_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials.save_credentials("spent", api_url=BASE_URL)
    monkeypatch.setattr(session, "login_user", _fake_login(calls := []))

    with Bookshelf(BASE_URL, transport=httpx.MockTransport(_api([], accept="fresh"))) as bs:
        user = bs.ensure_authenticated(interactive=True)

    assert user.email == USER["email"]
    assert calls == [BASE_URL]


@pytest.mark.parametrize(
    ("kwargs", "env"),
    [
        ({"auth": "explicit"}, {}),
        ({"auth": None}, {}),
        ({}, {"BOOKSHELF_TOKEN": "machine"}),
    ],
    ids=["explicit-token", "explicit-anonymous", "env-token"],
)
def test_a_credential_the_caller_chose_is_never_replaced(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any], env: dict[str, str]
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(session, "login_user", _fake_login(calls := []))
    transport = httpx.MockTransport(_api([], accept="fresh"))

    with (
        Bookshelf(BASE_URL, transport=transport, **kwargs) as bs,
        pytest.raises(AuthenticationRequiredError),
    ):
        bs.ensure_authenticated(interactive=True)

    assert calls == []


def test_drafting_without_a_credential_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session, "is_interactive", lambda: False)
    recorded: list[httpx.Request] = []

    transport = httpx.MockTransport(_api(recorded, accept=None))

    with (
        Bookshelf(BASE_URL, transport=transport) as bs,
        pytest.raises(AuthenticationRequiredError),
    ):
        bs.draft_book("primap-hist", version="1.0.0")

    assert recorded == []


def test_an_explicit_token_is_checked_before_drafting() -> None:
    recorded: list[httpx.Request] = []
    transport = httpx.MockTransport(_api(recorded, accept="fresh"))

    with (
        Bookshelf(BASE_URL, auth="stale", transport=transport) as bs,
        pytest.raises(AuthenticationRequiredError, match="auth="),
    ):
        bs.draft_book("primap-hist", version="1.0.0")

    assert [request.method for request in recorded] == ["GET"]


def test_an_anonymous_client_drafts_without_the_check() -> None:
    recorded: list[httpx.Request] = []

    transport = httpx.MockTransport(_api(recorded, accept=None))

    with (
        Bookshelf(BASE_URL, auth=None, transport=transport) as bs,
        pytest.raises(BookshelfError),
    ):
        bs.draft_book("primap-hist", version="1.0.0")

    assert [request.method for request in recorded] == ["POST"]


def test_a_terminal_without_a_browser_gets_a_device_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_browser() -> None:
        raise session.webbrowser.Error

    monkeypatch.setattr(session.webbrowser, "get", no_browser)
    chosen: list[bool] = []

    def login(api_url: str, *, browser: bool) -> tuple[models.UserResponse, StoredCredentials]:
        chosen.append(browser)
        return _fake_login([])(api_url, browser=browser)

    monkeypatch.setattr(session, "login_user", login)

    with Bookshelf(BASE_URL, transport=httpx.MockTransport(_api([], accept="fresh"))) as bs:
        bs.ensure_authenticated(interactive=True)

    assert chosen == [False]


def test_an_ssh_session_gets_a_device_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.1 22 10.0.0.2 22")

    assert not session._has_browser()


def test_a_spent_login_is_replaced_without_the_anonymous_warning(
    monkeypatch: pytest.MonkeyPatch, recwarn: pytest.WarningsRecorder
) -> None:
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client_test")
    monkeypatch.setenv("BOOKSHELF_WORKOS_BASE_URL", "https://workos.test")
    credentials.save_credentials("spent", api_url=BASE_URL, refresh_token="refused")
    monkeypatch.setattr(session, "login_user", _fake_login(calls := []))
    api = _api([], accept="fresh")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "workos.test":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return api(request)

    with Bookshelf(BASE_URL, transport=httpx.MockTransport(handler)) as bs:
        bs.ensure_authenticated(interactive=True)

    assert calls == [BASE_URL]
    assert not [w for w in recwarn if "continuing anonymously" in str(w.message)]


def test_a_spent_login_still_warns_after_a_refused_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_WORKOS_CLIENT_ID", "client_test")
    monkeypatch.setenv("BOOKSHELF_WORKOS_BASE_URL", "https://workos.test")
    credentials.save_credentials("spent", api_url=BASE_URL, refresh_token="refused")
    api = _api([], accept="fresh")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "workos.test":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return api(request)

    with Bookshelf(BASE_URL, transport=httpx.MockTransport(handler)) as bs:
        with pytest.raises(AuthenticationRequiredError):
            bs.ensure_authenticated(interactive=False)
        with (
            pytest.warns(UserWarning, match="continuing anonymously"),
            pytest.raises(BookshelfError),
        ):
            bs.volume("primap-hist")


def test_a_saved_login_reports_the_expiry_it_stored() -> None:
    token = "header.eyJleHAiOiAyMDAwMDAwMDAwfQ.signature"

    record = credentials.save_credentials(token, api_url=f"{BASE_URL}/")

    assert record.expires_at is not None
    assert record.expires_at.timestamp() == 2_000_000_000
    assert record.api_url == BASE_URL


def test_a_failure_other_than_rejection_is_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials.save_credentials("stored", api_url=BASE_URL)
    monkeypatch.setattr(session, "login_user", _fake_login(calls := []))
    transport = httpx.MockTransport(lambda _request: httpx.Response(403, json={"detail": "no"}))

    with (
        Bookshelf(BASE_URL, transport=transport) as bs,
        pytest.raises(APIError) as raised,
    ):
        bs.ensure_authenticated(interactive=True)

    assert raised.value.status_code == 403
    assert not isinstance(raised.value, AuthenticationRequiredError)
    assert calls == []


async def test_the_async_client_logs_in_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session, "is_interactive", lambda: True)
    monkeypatch.setattr(session, "login_user", _fake_login(calls := []))
    recorded: list[httpx.Request] = []
    transport = httpx.MockTransport(_api(recorded, accept="fresh"))

    async with AsyncBookshelf(BASE_URL, async_transport=transport) as bs:
        await bs.draft_book("primap-hist", version="1.0.0")
        user = await bs.ensure_authenticated()

    assert user.email == USER["email"]
    assert calls == [BASE_URL]
    assert recorded[-1].headers["Authorization"] == "Bearer fresh"
