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
from dataclasses import dataclass, field
from typing import Final

__all__ = ["FreePassError", "FreePasses", "PassEntry"]

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
class PassEntry:
    expiry: int
    calls: int
    owner: str
    # Analysis passes only (``app.limits.analysis_pass``): Neurons reserved or spent, and the
    # recorded documents (digest -> characters).
    neurons: int = 0
    documents: dict[str, int] = field(default_factory=dict)


class FreePasses:
    def __init__(  # noqa: PLR0913
        self,
        max_entries: int,
        max_calls: int,
        clock: Callable[[], float],
        *,
        ttl: int = TTL_SECONDS,
        audience: str = AUDIENCE,
        code_prefix: str = "free_pass",
    ) -> None:
        if max_entries < 1 or max_calls < 1 or ttl < 1:
            msg = "max_entries, max_calls and ttl must be positive"
            raise ValueError(msg)
        self._key = secrets.token_bytes(32)
        self._max_entries = max_entries
        self._max_calls = max_calls
        self._clock = clock
        self._ttl = ttl
        self._audience = audience
        self._prefix = code_prefix
        # nonce -> [expiry, calls]; the oldest pass first (the lifetime is fixed).
        self._table: dict[str, PassEntry] = {}
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
        self._table[nonce] = PassEntry(expiry, 1, owner)
        self._owner[owner] = nonce
        head = f"{VERSION}.{self._audience}.{expiry}.{owner}.{nonce}"
        return f"{head}.{self._digest(head)}", nonce

    def _error(self, kind: str) -> FreePassError:
        return FreePassError(f"{self._prefix}_{kind}")

    def lookup(self, value: str, client: str) -> tuple[str, PassEntry]:
        """Validate a pass for ``client`` and return its nonce and entry (no call counting).

        Raises ``FreePassError`` (``..._invalid`` or ``..._expired``)."""
        parts = value.split(".")
        if len(value) > MAX_PASS_CHARS or len(parts) != _PARTS:
            raise self._error("invalid")
        version, audience, expiry, owner, nonce, tag = parts
        shape_ok = (
            version == VERSION
            and audience == self._audience
            and _EXPIRY_RE.fullmatch(expiry) is not None
            and all(_HEX_RE.fullmatch(part) is not None for part in (owner, nonce, tag))
        )
        if not shape_ok:
            raise self._error("invalid")
        head = ".".join(parts[:-1])
        if not hmac.compare_digest(self._digest(head), tag):
            raise self._error("invalid")
        now = self._clock()
        if now >= int(expiry):
            raise self._error("expired")
        if not hmac.compare_digest(self._client(client), owner):
            raise self._error("invalid")
        entry = self._table.get(nonce)
        if entry is None:
            raise self._error("invalid")
        return nonce, entry

    def check(self, value: str, client: str) -> str:
        """Validate a pass for ``client`` and return its nonce; count nothing.

        Raises ``FreePassError``."""
        nonce, entry = self.lookup(value, client)
        if entry.calls >= self._max_calls:
            raise self._error("exhausted")
        return nonce

    def use(self, value: str, client: str) -> str:
        """Check a pass and count one call against it; return its nonce."""
        nonce = self.check(value, client)
        self._table[nonce].calls += 1
        return nonce

    def entry(self, nonce: str) -> PassEntry | None:
        """The live entry of ``nonce`` (for the analysis pass subclass)."""
        return self._table.get(nonce)

    def refund(self, nonce: str) -> None:
        """Give back one call of a pass whose call did no work (never below 1)."""
        entry = self._table.get(nonce)
        if entry is not None and entry.calls > 1:
            entry.calls -= 1

    def discard(self, nonce: str) -> None:
        """Forget a pass that was never handed out."""
        self._remove(nonce)
