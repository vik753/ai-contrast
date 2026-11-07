"""Map a quote of the neutralized clause text back to the source text (ADR 0019 point 2).

The model sees the clause after the prompt neutralization (``app.ai.prompting``): role tokens
and look-alike delimiters are broken with a space. Its quote may hold those changes. Every quote
is verified against the SOURCE text, so a quote that is not verbatim in the source is searched in
the neutralized view and replaced by the source text of the matching region. The result is always
a substring of the source. Pure; nothing is logged.
"""

from __future__ import annotations

from app.ai.prompting import FULLWIDTH_TABLE, NEUTRAL_STEPS
from app.analysis.verify import Clause, verify_quote

__all__ = ["NeutralView", "neutral_view", "source_quote"]


class NeutralView:
    """The neutralized text with, per character, the source range it comes from. A character
    made by a step maps to the whole source range of its match (wider, never narrower)."""

    __slots__ = ("ends", "starts", "text")

    def __init__(self, text: str, starts: list[int], ends: list[int]) -> None:
        self.text = text
        self.starts = starts
        self.ends = ends


def neutral_view(source: str) -> NeutralView | None:
    """``None`` when the neutralization leaves the text unchanged."""
    text = source.translate(FULLWIDTH_TABLE)
    starts = list(range(len(source)))
    ends = list(range(1, len(source) + 1))
    for pattern, template in NEUTRAL_STEPS:
        out: list[str] = []
        new_starts: list[int] = []
        new_ends: list[int] = []
        pos = 0
        for match in pattern.finditer(text):
            a, b = match.span()
            if a == b:
                continue
            out.append(text[pos:a])
            new_starts += starts[pos:a]
            new_ends += ends[pos:a]
            replacement = match.expand(template)
            out.append(replacement)
            new_starts += [starts[a]] * len(replacement)
            new_ends += [ends[b - 1]] * len(replacement)
            pos = b
        out.append(text[pos:])
        new_starts += starts[pos:]
        new_ends += ends[pos:]
        text, starts, ends = "".join(out), new_starts, new_ends
    if text == source:
        return None
    return NeutralView(text, starts, ends)


def source_quote(clause: Clause, quote: str, view: NeutralView | None) -> str:
    """``quote`` itself when it is verbatim in the source; else the source text of the region
    where it occurs in the neutralized view; else ``quote`` (it will not verify)."""
    if view is None or verify_quote(clause, quote).ok:
        return quote
    found = verify_quote(Clause(clause.id, view.text), quote)
    if not found.ok:
        return quote
    a, b = found.spans[0]
    return clause.text[view.starts[a] : view.ends[b - 1]]
