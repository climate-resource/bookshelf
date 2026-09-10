"""Tests for fetching the GitHub Actions OIDC token."""

import httpx
import pytest

from bookshelf._core import errors
from bookshelf._core.actions_oidc import ActionsTokenError, fetch_actions_token

REQUEST_URL = "https://actions.test/token?api-version=2.0"


@pytest.fixture
def actions_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_URL", REQUEST_URL)
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "runtime-bearer")


@pytest.mark.usefixtures("actions_env")
def test_the_token_is_requested_for_the_audience_with_the_runtime_bearer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"value": "oidc-jwt"})

    token = fetch_actions_token("bookshelf", transport=httpx.MockTransport(handler))

    assert token == "oidc-jwt"
    (request,) = seen
    assert request.url.params["api-version"] == "2.0"
    assert request.url.params["audience"] == "bookshelf"
    assert request.headers["authorization"] == "bearer runtime-bearer"


@pytest.mark.parametrize(
    "missing", ["ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
)
@pytest.mark.usefixtures("actions_env")
def test_a_missing_runtime_variable_names_the_permission(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing)

    with pytest.raises(ActionsTokenError, match="id-token: write"):
        fetch_actions_token("bookshelf")


@pytest.mark.usefixtures("actions_env")
def test_a_refusal_from_the_runtime_carries_the_status() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(403, text="denied"))

    with pytest.raises(ActionsTokenError, match="403"):
        fetch_actions_token("bookshelf", transport=transport)


@pytest.mark.usefixtures("actions_env")
def test_an_answer_without_a_value_is_refused() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"count": 1}))

    with pytest.raises(ActionsTokenError, match="without a token"):
        fetch_actions_token("bookshelf", transport=transport)


@pytest.mark.usefixtures("actions_env")
def test_an_unreachable_runtime_is_a_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(errors.TransportError):
        fetch_actions_token("bookshelf", transport=httpx.MockTransport(handler))
