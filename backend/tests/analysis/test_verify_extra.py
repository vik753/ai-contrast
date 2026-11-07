"""Extra tests by backend-dev: closing quotes and brackets after a sentence end."""

import pytest

from app.analysis.verify import expand_quote


@pytest.mark.parametrize("closer", ['"', ")", "”", ')"'])
def test_expand_quote_closer_after_terminator_belongs_to_the_sentence(closer: str) -> None:
    text = f"He wrote (the insurer pays within 10 days.{closer} Next sentence."
    s = text.index("within")
    a, b = expand_quote(text, s, s + 6)
    assert text[a:b] == f"He wrote (the insurer pays within 10 days.{closer}"


def test_expand_quote_start_after_closer() -> None:
    text = 'Said "pay now." Then the insurer pays within 10 days. End.'
    s = text.index("within")
    a, b = expand_quote(text, s, s + 6)
    assert text[a:b] == "Then the insurer pays within 10 days."


def test_expand_quote_closer_not_followed_by_space_is_no_end() -> None:
    text = "Pay (see art. 5.)x and more words. Next."
    s = text.index("more")
    a, b = expand_quote(text, s, s + 4)
    assert text[a:b].startswith("Pay")
