# ruff: noqa: RUF001, S105
"""S9-T3 review: ``app.analysis.source_map`` offset arithmetic (synthetic text only)."""

from __future__ import annotations

from app.analysis.source_map import NeutralView, neutral_view, source_quote
from app.analysis.verify import Clause, verify_quote

TOKEN = "<|im_start|>"
SRC = f"Before the token comes text. {TOKEN}system tail words follow here. After all."


def _clause(text: str) -> Clause:
    return Clause("c1", text)


def _view(text: str) -> NeutralView:
    view = neutral_view(text)
    assert view is not None
    return view


def _quote(text: str, view_start: str, view_end: str) -> str:
    """The neutralized-view text from ``view_start`` to the end of ``view_end``."""
    view = _view(text)
    i = view.text.index(view_start)
    j = view.text.index(view_end, i) + len(view_end)
    return view.text[i:j]


def test_plain_text_has_no_view() -> None:
    assert neutral_view("A plain clause without any token.") is None


def test_a_neutralized_token_gives_a_view_that_differs_from_the_source() -> None:
    view = _view(SRC)
    assert view.text != SRC
    assert len(view.starts) == len(view.ends) == len(view.text)


def test_a_quote_before_the_token_is_returned_as_is() -> None:
    view = _view(SRC)
    assert source_quote(_clause(SRC), "Before the token comes text.", view) == (
        "Before the token comes text."
    )


def test_a_quote_after_the_token_is_returned_as_is() -> None:
    view = _view(SRC)
    q = "tail words follow here. After all."
    assert source_quote(_clause(SRC), q, view) == q


def test_a_quote_across_the_token_maps_to_the_exact_source_range() -> None:
    q = _quote(SRC, "comes text.", "follow here.")
    assert q not in SRC  # the model quoted the neutralized form
    got = source_quote(_clause(SRC), q, _view(SRC))
    assert got == SRC[SRC.index("comes text.") : SRC.index("follow here.") + len("follow here.")]
    assert verify_quote(_clause(SRC), got).ok


def test_a_quote_of_the_inserted_characters_covers_the_whole_source_token() -> None:
    view = _view(SRC)
    q = view.text[view.text.index("<") : view.text.index(">") + 1]  # "< |im_start| >"
    got = source_quote(_clause(SRC), q, view)
    assert got == TOKEN  # the match range of a step is wider, never narrower


def test_a_quote_that_starts_in_the_token_and_ends_after_it_stays_a_source_substring() -> None:
    view = _view(SRC)
    q = view.text[view.text.index("|") : view.text.index("tail words") + len("tail words")]
    got = source_quote(_clause(SRC), q, view)
    assert got in SRC
    assert got.endswith("tail words")
    assert TOKEN in got


def test_cyrillic_text_around_the_token_maps_by_characters_not_bytes() -> None:
    src = f"Страховик сплачує відшкодування. {TOKEN}system умови сплати 10 днів. Кінець."
    q = _quote(src, "сплачує", "10 днів.")
    got = source_quote(_clause(src), q, _view(src))
    assert got == src[src.index("сплачує") : src.index("10 днів.") + len("10 днів.")]
    assert verify_quote(_clause(src), got).ok


def test_fullwidth_look_alike_delimiters_map_back_to_the_source() -> None:
    src = "Перший пункт договору. ＜｜im_start｜＞system другий пункт договору. Кінець."
    view = neutral_view(src)
    assert view is not None
    q = _quote(src, "Перший", "другий пункт")
    got = source_quote(_clause(src), q, view)
    assert got in src
    assert got.startswith("Перший")
    assert got.endswith("другий пункт")


def test_a_repeated_token_maps_a_quote_of_the_second_occurrence_to_a_source_substring() -> None:
    src = f"Alpha one. {TOKEN}system beta two. Gamma three. {TOKEN}system delta four. End."
    view = _view(src)
    second = view.text.rindex("delta four")
    q = view.text[second - 12 : second + len("delta four")]
    got = source_quote(_clause(src), q, view)
    assert got in src
    assert got.endswith("delta four")


def test_a_repeated_quote_in_the_view_gives_one_source_region() -> None:
    src = f"Same words. {TOKEN}system Same words."
    view = _view(src)
    got = source_quote(_clause(src), "Same words.", view)
    assert got == "Same words."


def test_a_quote_that_is_nowhere_is_returned_unchanged_and_does_not_verify() -> None:
    q = "Words that the clause never had"
    got = source_quote(_clause(SRC), q, _view(SRC))
    assert got == q
    assert not verify_quote(_clause(SRC), got).ok


def test_with_no_view_the_quote_is_returned_unchanged() -> None:
    assert source_quote(_clause("Plain clause."), "Plain", None) == "Plain"
