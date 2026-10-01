"""Transient retry policy: in-process backoff on rate limits, gateway failures and network failures.

Idempotent re-submission is the outage story, so the policy is deliberately light.
The client owns the loop and the sleeping.
Every decision inside that loop comes from this module.

A retry replays the request, so it is only safe when replaying cannot change the server state twice.
The policy therefore keys off the request method as well as the response status.
None of the write endpoints accept an idempotency key,
so a replayed POST or PATCH can commit the same registration, upload completion or publish twice.

A replay can also hurt the platform.
An expensive read that took a pod down lands on the next pod when replayed, and takes that one down too,
so an expensive read is never replayed after the server failed or went quiet on it.
"""

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

# Methods whose replay is safe by definition, so a retry cannot duplicate a write.
# PATCH is absent because HTTP does not define it as idempotent.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE"})

# A gateway or load balancer answering for a pod that restarted or was busy.
# A 500 is absent because it is the API failing on this request, which a replay repeats.
TRANSIENT_SERVER_ERRORS = frozenset({502, 503, 504})

# Refused before the API handled the request, so a replay is safe for any method.
RATE_LIMITED = 429


def parse_retry_after(value: str | None) -> float | None:
    """Seconds a ``Retry-After`` header asks the client to wait, or ``None`` when absent or unusable."""
    if value is None or not value.strip():
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (moment - datetime.now(UTC)).total_seconds())


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential backoff with equal jitter, so no replay follows immediately."""

    max_attempts: int = 3
    backoff_base: float = 1.0
    backoff_cap: float = 8.0
    max_retry_after: float = 30.0

    def should_retry_method(self, method: str) -> bool:
        """Whether replaying ``method`` is safe regardless of what the server already did."""
        return method.upper() in IDEMPOTENT_METHODS

    def should_retry_status(self, status_code: int) -> bool:
        return status_code in TRANSIENT_SERVER_ERRORS

    def should_retry_response(
        self, method: str, status_code: int, *, expensive: bool = False
    ) -> bool:
        if status_code == RATE_LIMITED:
            return True
        return (
            not expensive
            and self.should_retry_method(method)
            and self.should_retry_status(status_code)
        )

    def delay(self, attempt: int) -> float:
        """Sleep seconds before retry ``attempt`` (1-based: the first retry is attempt 1)."""
        ceiling = min(self.backoff_cap, self.backoff_base * (2 ** (attempt - 1)))
        return random.uniform(ceiling / 2, ceiling)

    def retry_after_response(
        self,
        method: str,
        attempt: int,
        status_code: int,
        *,
        retry_after: float | None = None,
        expensive: bool = False,
    ) -> float | None:
        """Seconds to sleep before replaying a request that came back with ``status_code``.

        None means stop, because the outcome is not retryable, because ``attempt`` used up the budget,
        or because the server asked for a longer wait than ``max_retry_after``.
        ``attempt`` is the attempt that just finished, counting from 1.
        """
        retryable = self.should_retry_response(method, status_code, expensive=expensive)
        if not retryable or attempt >= self.max_attempts:
            return None
        if retry_after is None:
            return self.delay(attempt)
        if retry_after > self.max_retry_after:
            return None
        # Jitter spreads the clients that were all told the same wait.
        return retry_after + random.uniform(0.0, self.backoff_base)

    def retry_after_transport_error(
        self, method: str, attempt: int, *, pre_send: bool, expensive: bool = False
    ) -> float | None:
        """Seconds to sleep before replaying a request that never came back with a response.

        None means stop, because the failure is not retryable or because ``attempt`` used up the budget.
        ``pre_send`` marks a failure that never reached the server,
        so replaying it cannot duplicate a write even for a non-idempotent method.
        """
        retryable = pre_send or (not expensive and self.should_retry_method(method))
        if not retryable or attempt >= self.max_attempts:
            return None
        return self.delay(attempt)
