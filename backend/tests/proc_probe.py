"""Look at the child processes of the test process through ``/proc`` (Linux).

Used by the sandbox tests (S3-T1, ADR 0011) to check from the outside what
the parsing child really runs with (limits, environment, arguments, working
directory) and that no child or zombie is left behind.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

PROC = Path("/proc")


def _state_and_ppid(pid: int) -> tuple[str, int] | None:
    try:
        raw = (PROC / str(pid) / "stat").read_text()
    except OSError:
        return None
    # The command name may contain spaces and parentheses: fields start after the last ")".
    fields = raw[raw.rindex(")") + 2 :].split()
    return fields[0], int(fields[1])


def descendants(root: int | None = None) -> dict[int, str]:
    """Every process below ``root`` (default: this process) -> its state letter."""
    root = os.getpid() if root is None else root
    table: dict[int, tuple[str, int]] = {}
    for entry in PROC.iterdir():
        if entry.name.isdigit():
            info = _state_and_ppid(int(entry.name))
            if info is not None:
                table[int(entry.name)] = info
    found: dict[int, str] = {}
    frontier = [root]
    while frontier:
        parent = frontier.pop()
        for pid, (state, ppid) in table.items():
            if ppid == parent and pid not in found:
                found[pid] = state
                frontier.append(pid)
    return found


def leftover_children(before: set[int]) -> dict[int, str]:
    """Descendants that did not exist in ``before``: live children and zombies."""
    return {pid: state for pid, state in descendants().items() if pid not in before}


def wait_until_no_leftovers(before: set[int], timeout: float = 5.0) -> dict[int, str]:
    """Give the parent a short moment to reap; return what is still there."""
    deadline = time.monotonic() + timeout
    left = leftover_children(before)
    while left and time.monotonic() < deadline:
        time.sleep(0.05)
        left = leftover_children(before)
    return left


def soft_limits(pid: int) -> dict[str, str]:
    """``/proc/<pid>/limits`` as ``{"Max file size": "0", ...}`` (soft limits)."""
    limits: dict[str, str] = {}
    lines = (PROC / str(pid) / "limits").read_text().splitlines()
    for line in lines[1:]:
        columns = re.split(r"\s{2,}", line.strip())
        if len(columns) >= 2:
            limits[columns[0]] = columns[1]
    return limits


def environ(pid: int) -> dict[str, str]:
    raw = (PROC / str(pid) / "environ").read_bytes()
    pairs = [item.split(b"=", 1) for item in raw.split(b"\x00") if item]
    return {k.decode("utf-8", "replace"): v.decode("utf-8", "replace") for k, v in pairs}


def cmdline(pid: int) -> list[str]:
    raw = (PROC / str(pid) / "cmdline").read_bytes()
    return [part.decode("utf-8", "replace") for part in raw.split(b"\x00") if part]


def cwd(pid: int) -> str:
    return str((PROC / str(pid) / "cwd").readlink())


async def wait_for_new_live_child(before: set[int], timeout: float = 15.0) -> int | None:
    """The first new descendant that is alive and has set ``RLIMIT_FSIZE`` to 0
    and ``RLIMIT_AS`` (the last limit it sets) to a finite value: the child is
    past its set-up. If none gets there, the last new live descendant seen, or
    ``None``."""
    deadline = time.monotonic() + timeout
    last: int | None = None
    while time.monotonic() < deadline:
        for pid, state in leftover_children(before).items():
            if state == "Z":
                continue
            last = pid
            try:
                limits = soft_limits(pid)
            except OSError:
                continue
            if limits.get("Max file size") == "0" and limits.get("Max address space") not in (
                None,
                "unlimited",
            ):
                return pid
        await asyncio.sleep(0.05)
    return last
