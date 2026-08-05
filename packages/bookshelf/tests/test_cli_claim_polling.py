"""Tests for the claim-ceremony polling loop (``bookshelf._cli.auth._poll_claim``)."""

from typing import Any

import pytest

from bookshelf._cli import auth
from bookshelf._cli._runtime import EXIT_AUTH_REQUIRED, CliError
from bookshelf._core.errors import OAuthProtocolError
from bookshelf._generated import models

GRANT = models.TokenResponse(
    access_token="bsat_claimed",
    token_type="Bearer",
    expires_in=3600,
    scope="read write",
)


class _StubClient:
    """Answer each exchange with the next queued outcome, an exception or a grant."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def agent_token_exchange(self, body: models.BodyAgentTokenExchange) -> models.TokenResponse:
        assert body.grant_type == auth.CLAIM_GRANT
        assert body.claim_token == "claim-1"
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[no-any-return]


def _protocol_error(error: str) -> OAuthProtocolError:
    return OAuthProtocolError("not yet.", error=error, status_code=400)


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture the polling waits instead of actually sleeping."""
    recorded: list[float] = []
    monkeypatch.setattr(auth.time, "sleep", recorded.append)
    return recorded


def _poll(client: Any, *, interval: int = 1, expires_in: int = 300) -> models.TokenResponse:
    return auth._poll_claim(
        client,
        claim_token="claim-1",
        interval=interval,
        expires_in=expires_in,
    )


def test_pending_polls_again_until_the_grant_arrives(waits: list[float]) -> None:
    client = _StubClient([_protocol_error("authorization_pending"), GRANT])

    assert _poll(client, interval=2) is GRANT
    assert client.calls == 2
    assert waits == [2]


def test_slow_down_adds_five_seconds_to_the_wait(waits: list[float]) -> None:
    client = _StubClient(
        [_protocol_error("slow_down"), _protocol_error("slow_down"), GRANT],
    )

    assert _poll(client, interval=2) is GRANT
    assert waits == [7, 12]


def test_a_zero_interval_still_waits_a_second(waits: list[float]) -> None:
    client = _StubClient([_protocol_error("authorization_pending"), GRANT])

    _poll(client, interval=0)

    assert waits == [1]


def test_any_other_oauth_error_names_the_retry_command(waits: list[float]) -> None:
    client = _StubClient([_protocol_error("access_denied")])

    with pytest.raises(CliError) as raised:
        _poll(client)

    assert raised.value.exit_code == EXIT_AUTH_REQUIRED
    assert "claim was not completed" in str(raised.value)
    assert "bookshelf auth login --agent --claim" in str(raised.value)
    assert waits == []


def test_an_expired_ceremony_stops_polling(waits: list[float]) -> None:
    client = _StubClient([_protocol_error("authorization_pending")])

    with pytest.raises(CliError) as raised:
        _poll(client, expires_in=0)

    assert raised.value.exit_code == EXIT_AUTH_REQUIRED
    assert "expired before approval" in str(raised.value)
    assert waits == []
