"""Unit tests for the transient retry policy."""

from bookshelf._core.retry import RetryPolicy


def test_retries_5xx_only() -> None:
    policy = RetryPolicy()
    assert policy.should_retry_status(500)
    assert policy.should_retry_status(503)
    assert not policy.should_retry_status(429)
    assert not policy.should_retry_status(409)
    assert not policy.should_retry_status(200)


def test_delay_grows_and_is_capped() -> None:
    policy = RetryPolicy(backoff_base=1.0, backoff_cap=3.0)
    for attempt, ceiling in ((1, 1.0), (2, 2.0), (3, 3.0), (4, 3.0)):
        delays = [policy.delay(attempt) for _ in range(50)]
        assert all(0.0 <= delay <= ceiling for delay in delays)
