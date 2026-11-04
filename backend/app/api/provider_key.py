"""The ``X-Provider-Key`` header as a dependency (ADR 0016 point 5, threat model T1).

The key travels only in this header. The dependency never raises and never echoes the
value: the endpoint decides which error code applies. A key is 1 to 512 printable ASCII
characters (no space), sent once. It is wrapped in ``SecretStr`` at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from fastapi import Request
from pydantic import SecretStr

KEY_HEADER: Final = "x-provider-key"
_KEY_RE: Final = re.compile(r"[\x21-\x7e]{1,512}", re.ASCII)


@dataclass(frozen=True)
class ProviderKeyHeader:
    present: bool  # the header is in the request, valid or not
    key: SecretStr | None  # the key if the header is present once and valid, else ``None``


def provider_key_header(request: Request) -> ProviderKeyHeader:
    values = request.headers.getlist(KEY_HEADER)
    if len(values) == 1 and _KEY_RE.fullmatch(values[0]):
        return ProviderKeyHeader(present=True, key=SecretStr(values[0]))
    return ProviderKeyHeader(present=bool(values), key=None)
