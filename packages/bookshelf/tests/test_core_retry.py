"""Unit tests for the transient retry policy."""

from bookshelf._core.retry import RetryPolicy


def test_retries_transient_5xx_only() -> None:
    policy = RetryPolicy()
    assert policy.should_retry_status(500)
    assert policy.should_retry_status(503)
    assert not policy.should_retry_status(429)
    assert not policy.should_retry_status(409)
    assert not policy.should_retry_status(200)


def test_permanent_5xx_is_not_transient() -> None:
    policy = RetryPolicy()
    assert not policy.should_retry_status(501)
    assert not policy.should_retry_status(505)


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


def test_delay_grows_and_is_capped() -> None:
    policy = RetryPolicy(backoff_base=1.0, backoff_cap=3.0)
    for attempt, ceiling in ((1, 1.0), (2, 2.0), (3, 3.0), (4, 3.0)):
        delays = [policy.delay(attempt) for _ in range(50)]
        assert all(0.0 <= delay <= ceiling for delay in delays)


def test_the_final_attempt_never_sleeps() -> None:
    policy = RetryPolicy(max_attempts=3)
    assert policy.retry_after_response("GET", 2, 503) is not None
    assert policy.retry_after_response("GET", 3, 503) is None
    assert policy.retry_after_transport_error("GET", 3, pre_send=True) is None


def test_a_response_that_is_not_retryable_ends_the_loop() -> None:
    policy = RetryPolicy()
    assert policy.retry_after_response("GET", 1, 503) is not None
    assert policy.retry_after_response("GET", 1, 200) is None
    assert policy.retry_after_response("GET", 1, 501) is None


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
