"""Describe an exception by its type names only (never its message)."""

from __future__ import annotations

# Limits against pathological (deeply nested or huge) exception groups.
MAX_GROUP_DEPTH = 8
MAX_GROUP_MEMBERS = 32


def exception_type_names(exc: BaseException, _depth: int = 0) -> str:
    """``ValueError``, or for groups ``ExceptionGroup(ValueError,KeyError)``, recursively.

    Only class names: exception messages may hold API keys or contract text.
    """
    name = type(exc).__name__
    if not isinstance(exc, BaseExceptionGroup):
        return name
    if _depth >= MAX_GROUP_DEPTH:
        return f"{name}(...)"
    members = [
        exception_type_names(member, _depth + 1) for member in exc.exceptions[:MAX_GROUP_MEMBERS]
    ]
    if len(exc.exceptions) > MAX_GROUP_MEMBERS:
        members.append("...")
    return f"{name}({','.join(members)})"
