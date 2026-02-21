"""Lightweight in-app rate limiting.

Edge deployments often rely on perimeter controls (API Gateway / Cloud Armor).
This module provides a portable baseline limiter that works in all environments.

Scope
- Currently used for **device ingest** (rate limit by device_id).
- Implemented as an in-memory token bucket.

Caveats
- In-memory state is per-process/per-instance.
  - On Cloud Run with multiple instances, the effective fleet-wide limit is higher.
- It is still useful as defense-in-depth and to prevent accidental overload.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .config import settings


@dataclass
class _Bucket:
    tokens: float
    updated_at: float
    last_seen_at: float


class TokenBucketLimiter:
    def __init__(
        self,
        *,
        capacity: int,
        refill_per_second: float,
        enabled: bool = True,
        idle_ttl_s: int = 3600,
    ) -> None:
        self.capacity = float(max(0, capacity))
        self.refill_per_second = float(max(0.0, refill_per_second))
        self.enabled = bool(enabled)
        self.idle_ttl_s = int(max(60, idle_ttl_s))

        self._lock = threading.Lock()
        self._buckets: Dict[str, _Bucket] = {}
        self._calls = 0

    def allow(self, *, key: str, cost: int = 1, now: Optional[float] = None) -> Tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""

        if not self.enabled:
            return True, 0

        if self.capacity <= 0 or self.refill_per_second <= 0:
            # Misconfigured; fail-open to avoid accidental outages.
            return True, 0

        if cost <= 0:
            return True, 0

        ts = float(now if now is not None else time.time())

        with self._lock:
            self._calls += 1
            if self._calls % 500 == 0:
                self._gc(ts)

            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=self.capacity, updated_at=ts, last_seen_at=ts)
                self._buckets[key] = b
            else:
                # Refill tokens since last update.
                delta = ts - b.updated_at
                if delta > 0:
                    b.tokens = min(self.capacity, b.tokens + delta * self.refill_per_second)
                    b.updated_at = ts
                b.last_seen_at = ts

            if float(cost) <= b.tokens:
                b.tokens -= float(cost)
                return True, 0

            # Not enough tokens. Compute a coarse retry-after.
            need = float(cost) - b.tokens
            retry_after = int(max(1.0, need / self.refill_per_second))
            return False, retry_after

    def _gc(self, now: float) -> None:
        """Remove idle buckets to keep memory bounded."""
        cutoff = now - float(self.idle_ttl_s)
        to_delete = [k for k, b in self._buckets.items() if b.last_seen_at < cutoff]
        for k in to_delete:
            self._buckets.pop(k, None)


# Device ingest: rate limit by "points per minute".
#
# Example: 25_000 points/min is far above normal field usage, but it still
# provides a meaningful cap for accidental high-rate replay loops.
_ingest_points_per_min = int(max(0, settings.ingest_rate_limit_points_per_min))
_ingest_refill_per_sec = float(_ingest_points_per_min) / 60.0 if _ingest_points_per_min > 0 else 0.0

ingest_points_limiter = TokenBucketLimiter(
    capacity=_ingest_points_per_min,
    refill_per_second=_ingest_refill_per_sec,
    enabled=settings.rate_limit_enabled,
)
