"""Shared builders for the S9-T1 tests (see README.md). Synthetic text only."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.analysis.verify import (
    Clause,
    DocumentContext,
    Evidence,
    Finding,
    NumericValue,
    Rating,
)


@dataclass(frozen=True)
class Lang:
    code: str
    base: str  # one long neutral sentence with "10 <days>"
    quote: str  # part of base
    short: str  # sentence under 25 characters
    exc: str  # sentence with an exception marker
    glob: str  # sentence with a global-override marker
    ref: str  # format string with {n}
    refto: str  # refers to clause number 1.1
    refnear: str  # refers to clause number 1.10 (not 1.1)
    heading_exc: str
    fifteen: str  # same sentence as base, 15 instead of 10
    two: str  # two day-numbers in one sentence
    words: str  # number in words and digits


LANGS = {
    "en": Lang(
        "en",
        "The insurer shall pay the claim within 10 days after receiving notice.",
        "within 10 days",
        "Pay in 10 days.",
        "Except in cases of intent, the insurer pays.",
        "Notwithstanding any other provision of this contract, the insurer decides.",
        "See clause {n}.",
        "Payment under clause 1.1 is limited.",
        "Payment under clause 1.10 is limited.",
        "Payment, except where excluded",
        "The insurer shall pay the claim within 15 days after receiving notice.",
        "The insurer pays within 10 days, but not later than 30 days after notice.",
        "The insurer shall pay the claim within ten (10) days after receiving notice.",
    ),
    "uk": Lang(
        "uk",
        "Страховик виплачує відшкодування протягом 10 днів після отримання повідомлення.",
        "протягом 10 днів",
        "Виплата за 10 днів.",
        "За винятком випадків умислу, страховик сплачує.",
        "Цей пункт має переважну силу над іншими положеннями договору.",
        "Див. п. {n}.",
        "Виплата за п. 1.1 обмежена.",
        "Виплата за п. 1.10 обмежена.",
        "Виплата, за винятком виключень",
        "Страховик виплачує відшкодування протягом 15 днів після отримання повідомлення.",
        "Страховик платить протягом 10 днів, але не пізніше 30 днів після повідомлення.",
        "Страховик виплачує відшкодування протягом десять (10) днів після отримання повідомлення.",
    ),
    "ru": Lang(
        "ru",
        "Страховщик выплачивает возмещение в течение 10 дней после получения уведомления.",
        "в течение 10 дней",
        "Выплата за 10 дней.",
        "За исключением случаев умысла, страховщик платит.",
        "Настоящий пункт имеет преимущественную силу над другими положениями договора.",
        "См. п. {n}.",
        "Выплата по п. 1.1 ограничена.",
        "Выплата по п. 1.10 ограничена.",
        "Выплата, за исключением исключений",
        "Страховщик выплачивает возмещение в течение 15 дней после получения уведомления.",
        "Страховщик платит в течение 10 дней, но не позднее 30 дней после уведомления.",
        "Страховщик выплачивает возмещение в течение десять (10) дней после получения уведомления.",
    ),
}
LANG_IDS = list(LANGS)

DAYS10 = NumericValue(Decimal(10), "days")


def c(cid: str, text: str, number: str | None = None, heading: str = "") -> Clause:
    return Clause(id=cid, text=text, heading=heading, number=number)


def ev(cid: str, quote: str) -> Evidence:
    return Evidence(clause=cid, quote=quote)


def ctx(*clauses: Clause, **kw: object) -> DocumentContext:
    return DocumentContext(clauses=tuple(clauses), **kw)  # type: ignore[arg-type]


def green(
    cid: str = "c1",
    quote: str = "",
    topic: str | None = "t1",
    value: NumericValue | None = None,
) -> Finding:
    return Finding(
        rating=Rating.green,
        evidence=(ev(cid, quote),),
        topic=topic,
        attribute="a1",
        value=value,
    )


def span_of(clause: Clause, quote: str) -> tuple[int, int]:
    i = clause.text.index(quote)
    return i, i + len(quote)
