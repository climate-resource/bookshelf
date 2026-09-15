"""Confirming a client's credential, and logging in when a person can."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from bookshelf import AsyncBookshelf, AuthenticationRequiredError, Bookshelf
from bookshelf._core import credentials, session
from bookshelf._core.credentials import StoredCredentials
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
