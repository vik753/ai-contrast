"""Per-request rate-limit hits of a minute and a day limiter, with refund of only what was counted.

One ``Hits`` serves the connection check and the topic endpoints; each passes its own limiters.
The minute key is the client key (an IPv6 /64); the day key is the daily key (a /48).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.limits.window import Decision, FixedWindowLimiter

__all__ = ["Hits"]


@dataclass
class Hits:
    minute_limiter: FixedWindowLimiter
    day_limiter: FixedWindowLimiter
    minute_key: str
    day_key: str
    minute: bool = False
    day: bool = False

    def count(self) -> Decision | None:
        """Count one hit on both limiters. ``None`` when counted, else the refusing decision
        (nothing stays counted)."""
        decision = self.minute_limiter.hit(self.minute_key)
        if not decision.allowed:
            return decision
        self.minute = True
        decision = self.day_limiter.hit(self.day_key)
        if not decision.allowed:
            self.refund()
            return decision
        self.day = True
        return None

    def refund(self) -> None:
        if self.day:
            self.day_limiter.refund(self.day_key)
            self.day = False
        if self.minute:
            self.minute_limiter.refund(self.minute_key)
            self.minute = False
