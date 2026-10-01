"""Unit tests for the transient retry policy."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from bookshelf._core.retry import RetryPolicy, parse_retry_after


def test_retries_gateway_failures_only() -> None:
    policy = RetryPolicy()
    for status in (502, 503, 504):
        assert policy.should_retry_status(status)
    for status in (200, 409, 429, 500, 501, 505):
        assert not policy.should_retry_status(status)


def test_only_idempotent_methods_are_replayable() -> None:
    policy = RetryPolicy()
    for method in ("GET", "head", "PUT", "DELETE", "OPTIONS", "TRACE"):
        assert policy.should_retry_method(method)
    for method in ("POST", "PATCH"):
        assert not policy.should_retry_method(method)


def test_a_write_is_never_retried_on_a_transient_status() -> None:
    policy = RetryPolicy()
    assert policy.should_retry_response("GET", 503)
    assert not policy.should_retry_response("POST", 503)
    assert not policy.should_retry_response("PATCH", 502)
    assert not policy.should_retry_response("GET", 501)


def test_a_rate_limit_is_retried_for_any_method() -> None:
    policy = RetryPolicy()
    for method in ("GET", "POST", "PATCH"):
        assert policy.should_retry_response(method, 429)
        assert policy.should_retry_response(method, 429, expensive=True)


def test_an_expensive_read_is_not_retried_on_a_server_failure() -> None:
    policy = RetryPolicy()
    assert not policy.should_retry_response("GET", 502, expensive=True)
    assert policy.retry_after_transport_error("GET", 1, pre_send=False, expensive=True) is None
    assert policy.retry_after_transport_error("GET", 1, pre_send=True, expensive=True) is not None


def test_delay_has_a_floor_and_is_capped() -> None:
    policy = RetryPolicy(backoff_base=1.0, backoff_cap=3.0)
    for attempt, ceiling in ((1, 1.0), (2, 2.0), (3, 3.0), (4, 3.0)):
        delays = [policy.delay(attempt) for _ in range(50)]
        assert all(ceiling / 2 <= delay <= ceiling for delay in delays)


def test_retry_after_is_honoured_with_jitter() -> None:
    policy = RetryPolicy(backoff_base=1.0)
    delays = [policy.retry_after_response("GET", 1, 429, retry_after=5.0) for _ in range(50)]
    assert all(delay is not None and 5.0 <= delay <= 6.0 for delay in delays)


def test_a_retry_after_beyond_the_ceiling_stops() -> None:
    policy = RetryPolicy(max_retry_after=10.0)
    assert policy.retry_after_response("GET", 1, 429, retry_after=11.0) is None
    assert policy.retry_after_response("GET", 1, 503, retry_after=11.0) is None


def test_the_final_attempt_never_sleeps() -> None:
    policy = RetryPolicy(max_attempts=3)
    assert policy.retry_after_response("GET", 2, 503) is not None
    assert policy.retry_after_response("GET", 3, 503) is None
    assert policy.retry_after_response("GET", 3, 429) is None
    assert policy.retry_after_transport_error("GET", 3, pre_send=True) is None


def test_a_response_that_is_not_retryable_ends_the_loop() -> None:
    policy = RetryPolicy()
    assert policy.retry_after_response("GET", 1, 503) is not None
    assert policy.retry_after_response("GET", 1, 200) is None
    assert policy.retry_after_response("GET", 1, 500) is None


def test_a_write_is_never_replayed_after_a_transient_status() -> None:
    policy = RetryPolicy()
    assert policy.retry_after_response("POST", 1, 503) is None
    assert policy.retry_after_response("PATCH", 1, 502) is None


def test_a_transport_failure_follows_the_method() -> None:
    policy = RetryPolicy()
    assert policy.retry_after_transport_error("GET", 1, pre_send=False) is not None
    assert policy.retry_after_transport_error("POST", 1, pre_send=False) is None


def test_a_pre_send_failure_is_replayable_even_for_a_write() -> None:
    policy = RetryPolicy()
    assert policy.retry_after_transport_error("POST", 1, pre_send=True) is not None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("7", 7.0), (" 0 ", 0.0), ("-3", None), ("soon", None)],
)
def test_parse_retry_after_seconds(value: str | None, expected: float | None) -> None:
    assert parse_retry_after(value) == expected


def test_parse_retry_after_http_date() -> None:
    later = datetime.now(UTC) + timedelta(seconds=120)
    parsed = parse_retry_after(format_datetime(later, usegmt=True))
    assert parsed is not None and 100 <= parsed <= 120


def test_parse_retry_after_past_date_is_zero() -> None:
    earlier = datetime.now(UTC) - timedelta(seconds=120)
    assert parse_retry_after(format_datetime(earlier, usegmt=True)) == 0.0
