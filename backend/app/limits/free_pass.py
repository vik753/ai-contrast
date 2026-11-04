"""Free pass for topic calls (ADR 0017 point 6; threat model T10).

A verified Turnstile token at the first free topic call buys a pass:
``v1.<aud>.<expiry>.<client-key-hash>.<nonce>.<mac>``. ``aud`` is ``topics``. The MAC is
HMAC-SHA256 over the first five parts with a per-process key (``secrets.token_bytes(32)``,
never stored, never logged): a restart invalidates every pass. The client hash binds the
pass to one client key (an IPv4 address or an IPv6 /48). Calls are counted per nonce in a
bounded table; a full table of live passes refuses new passes (fails closed). Callers run on
the event loop thread and no method awaits. Nothing here logs.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

__all__ = ["FreePassError", "FreePasses"]

VERSION: Final = "v1"
AUDIENCE: Final = "topics"
TTL_SECONDS: Final = 900
MAX_PASS_CHARS: Final = 256
_PARTS: Final = 6
_EXPIRY_RE: Final = re.compile(r"[0-9]{1,12}", re.ASCII)
_HEX_RE: Final = re.compile(r"[0-9a-f]{16,64}", re.ASCII)
_CLIENT_HEX: Final = 24


class FreePassError(Exception):
    """A pass is refused. ``code`` is ``free_pass_invalid``, ``_expired`` or ``_exhausted``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class _Entry:
    expiry: int
    calls: int
    owner: str


class FreePasses:
    def __init__(
        self,
        max_entries: int,
        max_calls: int,
        clock: Callable[[], float],
        *,
        ttl: int = TTL_SECONDS,
    ) -> None:
        if max_entries < 1 or max_calls < 1 or ttl < 1:
            msg = "max_entries, max_calls and ttl must be positive"
            raise ValueError(msg)
        self._key = secrets.token_bytes(32)
        self._max_entries = max_entries
        self._max_calls = max_calls
        self._clock = clock
        self._ttl = ttl
        # nonce -> [expiry, calls]; the oldest pass first (the lifetime is fixed).
        self._table: dict[str, _Entry] = {}
        # client hash -> nonce of its one live pass (a new solve replaces the old pass).
        self._owner: dict[str, str] = {}

    def _digest(self, text: str) -> str:
        return hmac.new(self._key, text.encode("ascii"), hashlib.sha256).hexdigest()

    def _client(self, client: str) -> str:
        return self._digest("client:" + client)[:_CLIENT_HEX]

    def _drop_expired(self, now: float) -> None:
        while self._table:
            oldest = next(iter(self._table))
            if now < self._table[oldest].expiry:
                return
            self._remove(oldest)

    def _remove(self, nonce: str) -> None:
        entry = self._table.pop(nonce, None)
        if entry is not None and self._owner.get(entry.owner) == nonce:
            del self._owner[entry.owner]

    def has_room(self, client: str) -> bool:
        """Can a pass be issued to ``client`` now? A client with a live pass replaces it."""
        self._drop_expired(self._clock())
        return self._client(client) in self._owner or len(self._table) < self._max_entries

    def issue(self, client: str) -> tuple[str, str] | None:
        """A new pass for ``client`` (call 1 is the issuing call): ``(pass, nonce)``.

        The pass that ``client`` held before stops working. ``None`` when the table is full of
        live passes and ``client`` has none."""
        now = self._clock()
        self._drop_expired(now)
        owner = self._client(client)
        old = self._owner.get(owner)
        if old is not None:
            self._remove(old)
        elif len(self._table) >= self._max_entries:
            return None
        expiry = int(now) + self._ttl
        nonce = secrets.token_hex(16)
        self._table[nonce] = _Entry(expiry, 1, owner)
        self._owner[owner] = nonce
        head = f"{VERSION}.{AUDIENCE}.{expiry}.{owner}.{nonce}"
        return f"{head}.{self._digest(head)}", nonce

    def check(self, value: str, client: str) -> str:
        """Validate a pass for ``client`` and return its nonce; count nothing.

        Raises ``FreePassError``."""
        parts = value.split(".")
        if len(value) > MAX_PASS_CHARS or len(parts) != _PARTS:
            raise FreePassError("free_pass_invalid")
        version, audience, expiry, owner, nonce, tag = parts
        shape_ok = (
            version == VERSION
            and audience == AUDIENCE
            and _EXPIRY_RE.fullmatch(expiry) is not None
            and all(_HEX_RE.fullmatch(part) is not None for part in (owner, nonce, tag))
        )
        if not shape_ok:
            raise FreePassError("free_pass_invalid")
        head = ".".join(parts[:-1])
        if not hmac.compare_digest(self._digest(head), tag):
            raise FreePassError("free_pass_invalid")
        now = self._clock()
        if now >= int(expiry):
            raise FreePassError("free_pass_expired")
        if not hmac.compare_digest(self._client(client), owner):
            raise FreePassError("free_pass_invalid")
        entry = self._table.get(nonce)
        if entry is None:
            raise FreePassError("free_pass_invalid")
        if entry.calls >= self._max_calls:
            raise FreePassError("free_pass_exhausted")
        return nonce

    def use(self, value: str, client: str) -> str:
        """Check a pass and count one call against it; return its nonce."""
        nonce = self.check(value, client)
        self._table[nonce].calls += 1
        return nonce

    def refund(self, nonce: str) -> None:
        """Give back one call of a pass whose call did no work (never below 1)."""
        entry = self._table.get(nonce)
        if entry is not None and entry.calls > 1:
            entry.calls -= 1

    def discard(self, nonce: str) -> None:
        """Forget a pass that was never handed out."""
        self._remove(nonce)
