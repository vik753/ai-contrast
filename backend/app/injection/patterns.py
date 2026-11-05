# ruff: noqa: RUF001
"""Layer 2 pattern data (ADR 0009 Layer 2, ADR 0017 point 4). Checked in and versioned.

Every word list below is written in natural spelling and folded (NFKC, confusable skeleton,
lower case) when ``app.injection.scanner`` loads it, so a look-alike spelling meets the same
entry. An entry that ends with ``*`` is a prefix (a stem that covers case forms in Ukrainian
and Russian); any other entry is a whole word. ``PATTERNS_VERSION`` is derived from the
lists below (every all-caps tuple of strings), so a change of a list changes it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

# Fixed strings of special, role and tag tokens. Always class "high".
FIXED_TOKENS: Final = (
    "<s>",
    "</s>",
    "[inst]",
    "[/inst]",
    "<<sys>>",
    "<</sys>>",
    "<start_of_turn>",
    "<end_of_turn>",
    "<<<begin",
    "<<<end",
)

# Our tag names, with or without attributes: the name must be followed by a blank or ">".
TAG_PREFIXES: Final = ("<document", "</document")

# `Human:` and `Assistant:` at the start of a line (after a few blanks, a blank before the
# colon is allowed). Class "high".
ROLE_LABELS: Final = ("human", "assistant")
# At most this many blanks before a role label and between it and the colon.
ROLE_BLANKS: Final = 16

# "ignore previous instructions": a verb, then within eight words a target.
IGNORE_VERBS: Final = (
    "ignore",
    "ignoring",
    "disregard",
    "disregarding",
    "forget",
    "override",
    "bypass",
    "ігнору*",
    "ігнорув*",
    "забудь*",
    "забуд*",
    "забыт*",
    "забыв*",
    "проігнору*",
    "игнорир*",
    "игнорь*",
    "проигнорир*",
)
INSTRUCTION_TARGETS: Final = (
    "instruction*",
    "directive*",
    "command*",
    "prompt*",
    "rules",
    "guidelines",
    "directions",
    "інструкц*",
    "вказівк*",
    "команд*",
    "правил*",
    "промпт*",
    "инструкц*",
    "указани*",
)

# "forget everything above": an ignore verb, a word of ALL_WORDS, then within two more words
# a word of ABOVE_WORDS.
ALL_WORDS: Final = ("everything", "all", "anything", "все", "всё", "усе", "всі", "всем")
ABOVE_WORDS: Final = (
    "above",
    "before",
    "earlier",
    "prior",
    "вище*",
    "выше*",
    "раніше",
    "ранее",
    "прежн*",
    "попередн*",
    "предыдущ*",
)

# "instructions for the assistant": an instruction word (any of the synonyms and case forms),
# up to two linking words ("intended"), "for" or "to", up to two articles or possessives,
# then an AI word. An AI word of the strong list always counts. A weak one ("model", "system")
# counts when it ends the phrase (no word follows it) or a hidden qualifier stands before the
# instruction word ("Instructions for model X200" and "for system maintenance" are honest).
# A strong AI word right after the instruction word ("Инструкция ассистенту") counts too.
INSTRUCTION_WORDS: Final = (
    "instruction*",
    "directive*",
    "command*",
    "prompt*",
    "промпт*",
    "інструкц*",
    "вказівк*",
    "команд*",
    "инструкц*",
    "указани*",
)
FOR_WORDS: Final = ("for", "to", "для")
LINK_WORDS: Final = (
    "intended",
    "meant",
    "addressed",
    "directed",
    "given",
    "призначен*",
    "предназначен*",
    "адресован*",
)
THE_WORDS: Final = ("the", "a", "an", "our", "your", "this", "my", "its")
AI_WORDS: Final = (
    "assistant*",
    "ai",
    "llm",
    "gpt",
    "chatbot*",
    "асистент*",
    "ассистент*",
    "ии",
    "ші",
    "нейромереж*",
    "нейросет*",
    "чатбот*",
)
LANGUAGE_WORDS: Final = ("language", "мовн*", "языков*")
MODEL_WORDS: Final = ("model*", "модел*")
WEAK_AI_WORDS: Final = ("system", "systems", "model*", "систем*", "модел*")
# A word before the instruction word (up to two words back) that marks it as hidden or system.
HIDDEN_QUALIFIERS: Final = (
    "system",
    "hidden",
    "secret",
    "системн*",
    "прихован*",
    "скрыт*",
    "секретн*",
)

# "rate everything green": a rating verb, up to three linking words, a colour or favourable
# word in an instrumental form (UK, RU) or the plain word (EN). Not "safe".
BARE_VERBS_EN: Final = (
    "rate",
    "rated",
    "rates",
    "mark",
    "marked",
    "score",
    "scored",
    "classify",
    "classified",
    "label",
    "labeled",
    "labelled",
)
BARE_VERBS_UKRU: Final = ("оцін*", "оцен*")
BARE_FILLERS: Final = (
    "it",
    "this",
    "that",
    "these",
    "those",
    "them",
    "everything",
    "all",
    "each",
    "every",
    "any",
    "clause",
    "clauses",
    "section",
    "sections",
    "term",
    "terms",
    "contract",
    "contracts",
    "document",
    "documents",
    "as",
    "whole",
    "entire",
    "both",
    "все",
    "всё",
    "усе",
    "усі",
    "всі",
    "каждый",
    "кожен",
    "это",
    "це",
    "этот",
    "цей",
    "пункты",
    "пункти",
    "условия",
    "умови",
    "договор",
    "договір",
    "документ",
    "как",
    "як",
)
BARE_RATING_EN: Final = ("green", "favorable", "favourable")
BARE_RATING_UKRU: Final = (
    "зеленим",
    "зеленими",
    "зеленою",
    "зеленым",
    "зелеными",
    "зеленой",
    "вигідним",
    "вигідними",
    "вигідною",
    "выгодным",
    "выгодными",
    "выгодной",
    "сприятливим",
    "сприятливими",
    "сприятливою",
    "благоприятным",
    "благоприятными",
    "благоприятной",
)

# "system prompt".
SYSTEM_WORDS: Final = ("system", "системн*", "системный", "системний")
PROMPT_WORDS: Final = ("prompt", "prompts", "промпт*")

# "rate as green", "mark as favorable": a verb, up to three words, "as", a rating word.
RATE_VERBS: Final = (
    "rate",
    "rated",
    "rates",
    "mark",
    "marked",
    "classify",
    "classified",
    "label",
    "labeled",
    "labelled",
    "score",
    "scored",
    "оцін*",
    "оцен*",
    "пометь*",
    "отметь*",
    "классифиц*",
    "считай*",
    "познач*",
    "відзнач*",
    "класифік*",
    "вважай*",
)
AS_WORDS: Final = ("as", "как", "як")
# "deemed favorable".
DEEMED_WORDS: Final = ("deemed", "считается", "вважається")
RATING_WORDS: Final = (
    "green",
    "favorable",
    "favourable",
    "safe",
    "зелен*",
    "выгодн*",
    "безопасн*",
    "благоприятн*",
    "вигідн*",
    "безпечн*",
    "сприятлив*",
)

# Topic meta-word rule (ADR 0017 point 3 rule 6; topics only). A topic text is refused when a
# word belongs to INSTRUCTION_WORDS or AI_WORDS, when "language model" appears
# (LANGUAGE_WORDS then MODEL_WORDS), or when a rating verb is followed by a colour or
# favourable word in any form (only BARE_FILLERS may stand between). "rating" counts only
# before "as".
META_RATE_VERBS: Final = ("rate", "rated", "rates", "оцін*", "оцен*")
META_RATING_AS: Final = ("rating",)
META_RATING_WORDS: Final = (
    "green",
    "favorable",
    "favourable",
    "зелен*",
    "вигідн*",
    "выгодн*",
    "благоприятн*",
    "сприятлив*",
)

# How far (in view characters) an instruction and a rating command must be to count as one
# high-class hit.
COMBINE_DISTANCE: Final = 500
# A run of this many base64 characters (letters, digits, `+`, `/`).
BASE64_MIN_RUN: Final = 100
# ... that has at least this many different characters.
BASE64_MIN_DISTINCT: Final = 10
# At most this many hits are kept; a text with more is still flagged.
MAX_HITS: Final = 1000


def _derive_version() -> str:
    """``pat-`` and 16 hex characters of the SHA-256 of all pattern lists (compact sorted JSON)."""
    lists = {
        name: list(value)
        for name, value in list(globals().items())
        if name.isupper()
        and name != "PATTERNS_VERSION"
        and isinstance(value, tuple)
        and all(isinstance(item, str) for item in value)
    }
    blob = json.dumps(lists, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "pat-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


PATTERNS_VERSION: Final = _derive_version()
