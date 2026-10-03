"""Tests for credential resolution: explicit beats ambient, machine beats human."""

import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from bookshelf._core import credentials, oauth
from bookshelf._core.auth import (
    ActionsOidcToken,
    AnonymousFallback,
    BsatAssertion,
    ClientCredentials,
    RefreshTokenExchange,
    StaticToken,
)
from bookshelf._core.credentials import CredentialKind, MemoryCredentialStore, StoredCredentials
from bookshelf._core.errors import AuthConfigurationError, AuthenticationError
from bookshelf._core.resolution import CredentialSource, resolve_credential

API = "https://bookshelf-staging.ovh.climateresource.com.au"
MACHINE = {
    "BOOKSHELF_CLIENT_ID": "cid",
    "BOOKSHELF_CLIENT_SECRET": "secret",
    "BOOKSHELF_TOKEN_URL": "https://issuer.test/token",
}


@pytest.fixture(autouse=True)
def no_workos_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOKSHELF_WORKOS_CLIENT_ID", raising=False)
    monkeypatch.delenv("BOOKSHELF_WORKOS_BASE_URL", raising=False)


def user_login(**fields: object) -> StoredCredentials:
    values: dict[str, object] = {
        "access_token": "stored-tok",
        "api_url": API,
        "expires_at": datetime.fromtimestamp(time.time() + 10_000, tz=UTC),
        "refresh_token": "rt-stored",
        "subject": "reader@example.com",
        "organization_id": "org_123",
    }
    return StoredCredentials(**(values | fields))  # type: ignore[arg-type]


def stored(**fields: object) -> MemoryCredentialStore:
    return MemoryCredentialStore([user_login(**fields)])


@pytest.mark.parametrize(
    ("environ", "source", "provider"),
    [
        ({}, CredentialSource.STORED_LOGIN, RefreshTokenExchange),
        ({"BOOKSHELF_TOKEN": "env-tok"}, CredentialSource.ENV_TOKEN, StaticToken),
        (MACHINE, CredentialSource.CLIENT_CREDENTIALS, ClientCredentials),
        (
            MACHINE | {"BOOKSHELF_AUTH": "github-actions"},
            CredentialSource.ACTIONS_OIDC,
            ActionsOidcToken,
        ),
        (
            {"BOOKSHELF_AUTH": "github-actions", "BOOKSHELF_TOKEN": "env-tok"},
            CredentialSource.ENV_TOKEN,
            StaticToken,
        ),
    ],
)
def test_first_step_that_answers_wins(
    environ: dict[str, str], source: CredentialSource, provider: type
) -> None:
    credential = resolve_credential(API, environ=environ, store=stored())

    assert credential.source is source
    assert isinstance(credential.token_provider(), provider)


def test_nothing_found_resolves_to_no_credential() -> None:
    credential = resolve_credential(API, environ={}, store=MemoryCredentialStore())

    assert credential.source is CredentialSource.NONE
    assert credential.auth() is None
    assert credential.token_provider() is None


def test_actions_oidc_is_opt_in() -> None:
    environ = {
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://actions.test/token",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "runtime-bearer",
    }
    credential = resolve_credential(API, environ=environ, store=MemoryCredentialStore())

    assert credential.source is CredentialSource.NONE


def test_actions_oidc_mints_for_the_read_audience() -> None:
    credential = resolve_credential(
        API, environ={"BOOKSHELF_AUTH": "github-actions"}, store=MemoryCredentialStore()
    )

    provider = credential.token_provider()
    assert isinstance(provider, ActionsOidcToken)
    assert provider._audience == "bookshelf-read"


@pytest.mark.parametrize(
    "environ", [{"BOOKSHELF_AUTH": "gitlab"}, {"BOOKSHELF_AUTH": "gitlab", "BOOKSHELF_TOKEN": "t"}]
)
def test_an_unknown_auth_mode_is_named_even_when_a_token_wins(environ: dict[str, str]) -> None:
    with pytest.raises(AuthConfigurationError, match="github-actions"):
        resolve_credential(API, environ=environ, store=MemoryCredentialStore())


def test_client_credentials_without_token_url_is_an_error() -> None:
    environ = {"BOOKSHELF_CLIENT_ID": "cid", "BOOKSHELF_CLIENT_SECRET": "secret"}
    credential = resolve_credential(API, environ=environ, store=MemoryCredentialStore())

    with pytest.raises(AuthConfigurationError, match="BOOKSHELF_TOKEN_URL"):
        credential.auth()


def test_stored_login_is_looked_up_for_the_deployment_only() -> None:
    credential = resolve_credential("https://other.test", environ={}, store=stored())

    assert credential.source is CredentialSource.NONE


def test_stored_without_workos_client_id_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silently degrading to a static token would kill rotation mid-process."""
    monkeypatch.setattr(oauth, "resolve_workos_client_id", lambda _api_url: None)
    credential = resolve_credential(API, environ={}, store=stored())

    with pytest.raises(AuthConfigurationError):
        credential.auth()


def test_stored_without_refresh_token_resolves_to_static() -> None:
    credential = resolve_credential(API, environ={}, store=stored(refresh_token=None))

    provider = credential.token_provider()
    assert isinstance(provider, StaticToken)
    assert provider._token == "stored-tok"


def test_a_stored_agent_resolves_to_its_assertion() -> None:
    store = stored(kind=CredentialKind.AGENT, identity_assertion="ia", refresh_token=None)

    credential = resolve_credential(API, environ={}, store=store)

    assert isinstance(credential.token_provider(), BsatAssertion)


def test_the_provider_is_built_once() -> None:
    credential = resolve_credential(API, environ={}, store=stored())

    auth = credential.auth()

    assert isinstance(auth, AnonymousFallback)
    assert auth.inner is credential.token_provider()
    assert credential.auth() is auth
    assert credential.auth(strict=True) is credential.token_provider()


def token_endpoint(status: int, body: Mapping[str, object]) -> httpx.MockTransport:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authenticate"):
            return httpx.Response(status, json=body)
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    transport.seen = seen  # type: ignore[attr-defined]
    return transport


ROTATED = {"access_token": "new-tok", "refresh_token": "rt-2", "expires_in": 3600}


def test_a_refresh_is_written_back_without_moving_the_default() -> None:
    store = stored(expires_at=datetime.fromtimestamp(0, tz=UTC))
    store.save_login(StoredCredentials(access_token="prod-tok", api_url="https://prod.test"))

    auth = resolve_credential(API, environ={}, store=store).auth()
    with httpx.Client(transport=token_endpoint(200, ROTATED), auth=auth) as client:
        client.get(f"{API}/v1/books")

    rotated = store.load(API)
    assert rotated is not None
    assert (rotated.access_token, rotated.refresh_token) == ("new-tok", "rt-2")
    assert rotated.subject == "reader@example.com"
    assert rotated.organization_id == "org_123"
    default = store.load()
    assert default is not None
    assert default.api_url == "https://prod.test"


def test_consecutive_refreshes_each_replace_the_last() -> None:
    store = stored(expires_at=datetime.fromtimestamp(0, tz=UTC))
    provider = resolve_credential(API, environ={}, store=store).token_provider()
    assert isinstance(provider, RefreshTokenExchange)

    with httpx.Client(transport=token_endpoint(200, ROTATED)) as client:
        provider.access_token(client.send)
        provider._expires_at = 0.0
        provider.access_token(client.send)

    assert [record.access_token for record in store.records()] == ["new-tok"]


def test_an_agent_record_without_an_assertion_rotates_its_refresh_token() -> None:
    store = stored(
        kind=CredentialKind.AGENT,
        identity_assertion=None,
        expires_at=datetime.fromtimestamp(0, tz=UTC),
    )

    auth = resolve_credential(API, environ={}, store=store).auth()
    with httpx.Client(transport=token_endpoint(200, ROTATED), auth=auth) as client:
        client.get(f"{API}/v1/books")

    rotated = store.load(API)
    assert rotated is not None
    assert rotated.kind is CredentialKind.AGENT
    assert store.active_kinds() == {API: CredentialKind.AGENT}
    assert rotated.refresh_token == "rt-2"
    assert rotated.identity_assertion is None


REFUSED = {"error_description": "Refresh token already exchanged"}


def test_a_spent_stored_login_degrades_to_anonymous() -> None:
    """A refresh the issuer refuses must not cost the caller the public books."""
    store = stored(expires_at=datetime.fromtimestamp(0, tz=UTC))
    transport = token_endpoint(400, REFUSED)

    auth = resolve_credential(API, environ={}, store=store).auth()
    with (
        httpx.Client(transport=transport, auth=auth) as client,
        pytest.warns(UserWarning) as record,
    ):
        response = client.get(f"{API}/v1/books")

    assert response.status_code == 200
    assert transport.seen == [""]  # type: ignore[attr-defined]
    warning = str(record[0].message)
    assert "bookshelf auth logout" in warning
    assert "bookshelf auth login" in warning
    assert "Refresh token already exchanged" in warning


def test_a_strict_credential_raises_instead_of_degrading() -> None:
    store = stored(expires_at=datetime.fromtimestamp(0, tz=UTC))

    auth = resolve_credential(API, environ={}, store=store).auth(strict=True)
    with (
        httpx.Client(transport=token_endpoint(400, REFUSED), auth=auth) as client,
        pytest.raises(AuthenticationError, match="already exchanged"),
    ):
        client.get(f"{API}/v1/books")


@pytest.mark.parametrize(
    ("environ", "kind", "label"),
    [
        ({"BOOKSHELF_TOKEN": "bsat_tok"}, "agent", "$BOOKSHELF_TOKEN"),
        ({"BOOKSHELF_TOKEN": "tok"}, "user", "$BOOKSHELF_TOKEN"),
        ({"BOOKSHELF_AUTH": "github-actions"}, "machine", "GitHub Actions"),
        (MACHINE, "machine", "$BOOKSHELF_CLIENT_ID"),
        ({}, "anonymous", "no credential"),
    ],
)
def test_machine_and_missing_credentials_describe_themselves(
    environ: dict[str, str], kind: str, label: str
) -> None:
    described = resolve_credential(API, environ=environ, store=MemoryCredentialStore()).describe()

    assert described.kind == kind
    assert label in described.label


def test_a_stored_agent_describes_its_claim() -> None:
    store = stored(
        kind=CredentialKind.AGENT, identity_assertion="ia", subject="agent:1", claimed=False
    )

    described = resolve_credential(API, environ={}, store=store).describe()

    assert described.kind == "agent"
    assert described.subject == "agent:1"
    assert described.claimed is False


def test_only_a_person_may_replace_a_credential() -> None:
    for environ in ({"BOOKSHELF_TOKEN": "t"}, MACHINE, {"BOOKSHELF_AUTH": "github-actions"}):
        assert not resolve_credential(API, environ=environ, store=stored()).may_prompt_login()
    assert resolve_credential(API, environ={}, store=stored()).may_prompt_login()
    assert resolve_credential(API, environ={}, store=MemoryCredentialStore()).may_prompt_login()


def test_a_machine_credential_reports_the_login_it_shadows() -> None:
    store = stored()

    assert (
        resolve_credential(API, environ={"BOOKSHELF_TOKEN": "t"}, store=store).shadowed_login()
        is not None
    )
    assert resolve_credential(API, environ={}, store=store).shadowed_login() is None


def test_an_adopted_login_uses_the_new_record() -> None:
    credential = resolve_credential(API, environ={}, store=MemoryCredentialStore())

    adopted = credential.with_login(user_login(refresh_token=None))

    assert adopted.source is CredentialSource.STORED_LOGIN
    assert adopted.store is credential.store
    assert isinstance(adopted.token_provider(), StaticToken)


NEWER_API = "https://api.example"


def _store_file(path: Path, version: int, expires_at: str) -> str:
    text = json.dumps(
        {
            "version": version,
            "records": {
                f"{NEWER_API}|user": {
                    "access_token": "theirs",
                    "api_url": NEWER_API,
                    "kind": "user",
                    "refresh_token": "single-use",
                    "expires_at": expires_at,
                }
            },
            "active": {NEWER_API: "user"},
        }
    )
    path.write_text(text)
    return text


def _refuse_requests(request: httpx.Request) -> httpx.Response:
    pytest.fail(f"no request expected, got {request.url}")


@pytest.fixture
def workos_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oauth, "resolve_workos_client_id", lambda _url: "client")


@pytest.mark.usefixtures("workos_client_id")
def test_a_newer_store_serves_a_live_token_without_refreshing(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    _store_file(path, credentials.STORE_VERSION + 1, "2999-01-01T00:00:00+00:00")
    store = credentials.FileCredentialStore(path)

    provider = resolve_credential(NEWER_API, environ={}, store=store).token_provider()

    assert provider is not None
    assert provider.access_token(_refuse_requests) == "theirs"


@pytest.mark.usefixtures("workos_client_id")
def test_a_newer_store_refuses_to_refresh_an_expired_token(tmp_path: Path) -> None:
    """Refreshing would spend the single-use refresh token the newer install still needs."""
    path = tmp_path / "credentials.json"
    before = _store_file(path, credentials.STORE_VERSION + 1, "2000-01-01T00:00:00+00:00")
    store = credentials.FileCredentialStore(path)

    provider = resolve_credential(NEWER_API, environ={}, store=store).token_provider()

    assert provider is not None
    with pytest.raises(AuthenticationError, match="newer bookshelf"):
        provider.access_token(_refuse_requests)
    assert path.read_text() == before


@pytest.mark.usefixtures("workos_client_id")
def test_a_store_upgraded_after_resolution_is_not_refreshed_against(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    _store_file(path, credentials.STORE_VERSION, "2000-01-01T00:00:00+00:00")
    store = credentials.FileCredentialStore(path)
    provider = resolve_credential(NEWER_API, environ={}, store=store).token_provider()
    upgraded = _store_file(path, credentials.STORE_VERSION + 1, "2000-01-01T00:00:00+00:00")

    assert provider is not None
    with pytest.raises(AuthenticationError, match="newer bookshelf"):
        provider.access_token(_refuse_requests)
    assert path.read_text() == upgraded
