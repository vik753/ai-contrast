# ruff: noqa: RUF001
"""The stub oracle of the topic eval (S7-T4): a deterministic local stand-in for a model.

It writes ``recordings/stub__oracle-v1.json`` (``stub: true``). Its numbers test the harness,
never a model.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from app.ai.port import AIError, AIErrorCode, AIRequest, CheckResult, ModelJson
from app.ai.prompts import PromptTemplate
from app.pseudo.gate import PseudonymizedDocument

__all__ = ["MAX_SUGGESTIONS", "OracleProvider"]

MAX_SUGGESTIONS: Final = 8
_WORD: Final = re.compile(r"[^\W_]+")

_HEADING: Final = re.compile(r"\d{1,2}\.\s+([^\d\n\[][^\n\[]{0,58})")
_DESCRIPTION: Final = {
    "en": "What the contract says about this subject.",
    "uk": "Що договір каже про цю тему.",
    "ru": "Что договор говорит об этой теме.",
}
_ORACLE_RULES: Final = (
    # (name stems, id, type, labels en/uk/ru, units, values en/uk/ru)
    (
        ("term", "period", "review", "payout", "выплат", "виплат", "строк", "срок", "розгляд"),
        "term_days",
        "duration",
        ("Term in days", "Строк у днях", "Срок в днях"),
        ("days",),
        None,
    ),
    (
        ("indexation", "refund", "penalt", "штраф", "поверн", "возврат", "індекс", "индекс"),
        "rate_percent",
        "percentage",
        ("Rate, percent", "Ставка, відсоток", "Ставка, процент"),
        (),
        None,
    ),
    (
        ("assistance", "cover", "pet", "ремонт", "сигнал", "затоп", "комиссар", "тварин"),
        "included_items",
        "categories",
        ("Included items", "Що включено", "Что включено"),
        (),
        (("basic", "extended"), ("базовий", "розширений"), ("базовый", "расширенный")),
    ),
)


def _lang_of(text: str) -> str:
    lowered = text.lower()
    if not any("Ѐ" <= char <= "ӿ" for char in lowered):
        return "en"
    if any(char in "іїєґ" for char in lowered):
        return "uk"
    return "ru"


class OracleProvider:
    """A deterministic local stand-in for a model. Suggest: the section headings of the
    document (at most 8); for a document with an injection it answers like a fully
    compromised model. Propose: keyword rules. Expand: stems of the name in its own language
    only. It reads gate objects, as an adapter does, and never sees a raw string input."""

    def __init__(self, attack: Sequence[dict[str, str]]) -> None:
        self._attack = attack

    async def check(self) -> CheckResult:
        return CheckResult(ok=True)

    async def complete_json(self, request: AIRequest) -> ModelJson:
        if request.document is not None:
            return self._suggest(request.document)
        if request.topic is None:
            raise AIError(AIErrorCode.PROVIDER_BAD_REQUEST) from None
        if request.template is PromptTemplate.PROPOSE_ATTRIBUTES:
            return self._propose(request.topic.title)
        return self._expand(request.topic.title)

    def _suggest(self, document: PseudonymizedDocument) -> ModelJson:
        texts = [clause.text for clause in document.clauses]
        if any("SYSTEM NOTE FOR THE AI" in text for text in texts):
            # A compromised model; an answer holds at most 8 topics, so the first 8 items.
            attack = self._attack[:MAX_SUGGESTIONS]
            return {
                "topics": [{"name": a["name"], "description": a["description"]} for a in attack]
            }
        lang = _lang_of(" ".join(texts))
        names = [m.group(1).strip() for t in texts if (m := _HEADING.fullmatch(t.strip()))]
        topics = [{"name": n, "description": _DESCRIPTION[lang]} for n in names[:MAX_SUGGESTIONS]]
        return {"topics": topics}

    def _propose(self, name: str) -> ModelJson:
        index = ("en", "uk", "ru").index(_lang_of(name))
        lowered = name.lower()
        attributes: list[dict[str, object]] = [
            {
                "id": "limit_amount",
                "label": ("Limit amount", "Сума ліміту", "Сумма лимита")[index],
                "type": "amount",
                "units": ["UAH"],
            }
        ]
        for stems, attr_id, kind, labels, units, values in _ORACLE_RULES:
            if any(stem in lowered for stem in stems):
                item: dict[str, object] = {"id": attr_id, "label": labels[index], "type": kind}
                if units:
                    item["units"] = list(units)
                if values:
                    item["values"] = list(values[index])
                attributes.append(item)
        attributes.append(
            {"id": "conditions", "label": ("Conditions", "Умови", "Условия")[index], "type": "text"}
        )
        return {"attributes": attributes}

    def _expand(self, name: str) -> ModelJson:
        lang = _lang_of(name)
        words = [w.lower() for w in _WORD.findall(name) if len(w) >= 4]  # noqa: PLR2004
        stems = [w if lang == "en" else w[:6] for w in words]
        own = [name.lower(), *stems]
        lists: ModelJson = {"synonyms_en": [], "synonyms_uk": [], "synonyms_ru": []}
        lists[f"synonyms_{lang}"] = list(dict.fromkeys(own))
        return lists
