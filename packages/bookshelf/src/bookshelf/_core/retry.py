"""Transient retry policy: in-process backoff on 5xx and network failures only.

Idempotent re-submission is the outage story, so the policy is deliberately light.
The client handles the retry loop.

A retry replays the request, so it is only safe when replaying cannot change the server state twice.
The policy therefore keys off the request method as well as the response status.
None of the write endpoints accept an idempotency key,
so a replayed POST or PATCH can commit the same registration, upload completion or publish twice.
"""

import random
from dataclasses import dataclass

# Methods whose replay is safe by definition, so a retry cannot duplicate a write.
# PATCH is absent because HTTP does not define it as idempotent.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE"})

# 5xx codes that describe a permanent property of the server rather than a transient fault.
PERMANENT_SERVER_ERRORS = frozenset({501, 505})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential backoff with full jitter."""

    max_attempts: int = 3
    backoff_base: float = 0.25
    backoff_cap: float = 4.0

    def should_retry_method(self, method: str) -> bool:
        """Whether replaying ``method`` is safe regardless of what the server already did."""
        return method.upper() in IDEMPOTENT_METHODS

    def should_retry_status(self, status_code: int) -> bool:
        return 500 <= status_code < 600 and status_code not in PERMANENT_SERVER_ERRORS

    def should_retry_response(self, method: str, status_code: int) -> bool:
        return self.should_retry_method(method) and self.should_retry_status(status_code)

    def delay(self, attempt: int) -> float:
        """Sleep seconds before retry ``attempt`` (1-based: the first retry is attempt 1)."""
        ceiling = min(self.backoff_cap, self.backoff_base * (2 ** (attempt - 1)))
        return random.uniform(0.0, ceiling)
