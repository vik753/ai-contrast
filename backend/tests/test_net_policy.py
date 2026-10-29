"""S3-T6a item 3: outbound-network policy (ADR 0012 point 2).

No module under ``app/`` except ``app/net/`` may create an HTTP client or open a socket.
The scanner is checked on a bad snippet first, so the policy test cannot pass by scanning
nothing. ``ALLOWED`` lists modules outside ``app/net/`` that are allowed to use a banned
name (today none; add a path here with a comment if the sandbox needs one).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
ALLOWED: frozenset[str] = frozenset()

BANNED_MODULES = {
    "httpx",
    "httpcore",
    "httpx2",
    "httpcore2",
    "urllib3",
    "requests",
    "aiohttp",
    "urllib.request",
    "http.client",
}
BANNED_ATTRIBUTES = {"create_connection", "open_connection", "urlopen"}


def violations(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name in BANNED_MODULES]
            found += [a.name for a in node.names if a.name == "socket"]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in BANNED_MODULES or module.split(".")[0] in {
                "httpx",
                "httpcore",
                "httpx2",
                "httpcore2",
            }:
                found.append(module)
            if module == "urllib" and any(a.name in {"request"} for a in node.names):
                found.append("urllib.request")
            if module == "http" and any(a.name == "client" for a in node.names):
                found.append("http.client")
            if module == "socket":
                found.append("socket")
            if module == "asyncio" and any(a.name == "open_connection" for a in node.names):
                found.append("asyncio.open_connection")
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_ATTRIBUTES:
            found.append(node.attr)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in BANNED_ATTRIBUTES:
                found.append(fn.id)
    return found


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\n",
        "from httpx import AsyncClient\n",
        "import httpcore\n",
        "import urllib.request\n",
        "from urllib import request\n",
        "import http.client\n",
        "from http import client\n",
        "import socket\nsocket.create_connection(('a', 1))\n",
        "from socket import socket\n",
        "import asyncio\nasyncio.open_connection('a', 1)\n",
        "from asyncio import open_connection\n",
    ],
)
def test_policy_scanner_detects_banned_use(source: str) -> None:
    assert violations(source)


def test_policy_scanner_allows_harmless_imports() -> None:
    assert violations("import json\nfrom urllib.parse import urlsplit\nimport asyncio\n") == []


def test_policy_no_module_outside_app_net_uses_network_primitives() -> None:
    files = [
        path
        for path in APP.rglob("*.py")
        if "net" not in path.relative_to(APP).parts[:1]
        and path.relative_to(APP).as_posix() not in ALLOWED
    ]
    assert files, "the scan must see the application modules"

    offenders = {
        path.relative_to(APP).as_posix(): hits
        for path in files
        if (hits := violations(path.read_text(encoding="utf-8")))
    }

    assert offenders == {}
