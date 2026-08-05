"""Transient retry policy: in-process backoff on 5xx and network failures only.

Idempotent re-submission is the outage story, so the policy is deliberately light.
The client handles the retry loop.
"""

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential backoff with full jitter."""

    max_attempts: int = 3
    backoff_base: float = 0.25
    backoff_cap: float = 4.0

    def should_retry_status(self, status_code: int) -> bool:
        return status_code >= 500

    def delay(self, attempt: int) -> float:
        """Sleep seconds before retry ``attempt`` (1-based: the first retry is attempt 1)."""
        ceiling = min(self.backoff_cap, self.backoff_base * (2 ** (attempt - 1)))
        return random.uniform(0.0, ceiling)
