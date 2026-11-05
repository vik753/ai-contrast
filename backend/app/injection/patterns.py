"""Layer 2 pattern data (ADR 0009 Layer 2, ADR 0017 point 4). Checked in and versioned.
# ruff: noqa: RUF001

Every word list below is written in natural spelling and folded (NFKC, confusable skeleton,
lower case) when ``app.injection.scanner`` loads it, so a look-alike spelling meets the same
entry. An entry that ends with ``*`` is a prefix (a stem that covers case forms in Ukrainian
and Russian); any other entry is a whole word. Change a list: bump ``PATTERNS_VERSION``.
"""

from __future__ import annotations

from typing import Final

PATTERNS_VERSION: Final = "2026-11-04.2"

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
    "disregard",
    "forget",
    "override",
    "bypass",
    "ігнору*",
    "ігнорув*",
    "забудь*",
    "проігнору*",
    "игнорир*",
    "игнорь*",
    "проигнорир*",
)
INSTRUCTION_TARGETS: Final = (
    "instruction",
    "instructions",
    "prompt",
    "prompts",
    "rules",
    "guidelines",
    "directions",
    "інструкці*",
    "вказівк*",
    "правила",
    "промпт*",
    "инструкци*",
    "указани*",
)

# "forget everything above": an ignore verb, a word of ALL_WORDS, then within two more words
# a word of ABOVE_WORDS.
ALL_WORDS: Final = ("everything", "all", "anything", "все", "всё", "усе", "всі", "всем")  # noqa: RUF001
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

# "instructions for the assistant": an instruction word, "for" or "to", an optional "the",
# then an AI word. "System instruction" in Ukrainian or Russian is a hit on its own.
INSTRUCTION_WORDS: Final = ("instruction", "instructions", "інструкці*", "инструкци*")
FOR_WORDS: Final = ("for", "to", "для")
THE_WORDS: Final = ("the", "a", "an")
AI_WORDS: Final = (
    "assistant",
    "ai",
    "model",
    "llm",
    "chatbot",
    "system",
    "асистент*",
    "ассистент*",
    "модел*",
    "систем*",
    "чатбот*",
)
HIDDEN_QUALIFIERS: Final = ("системн*", "прихован*", "скрыт*", "секретн*")

# "rate everything green": a bare rating command, no "as".
QUANTIFIER_WORDS: Final = ("everything", "all", "every", "each", "any")
RATE_BARE_EN: Final = ("rate", "mark", "score", "classify", "label")
RATE_BARE_UKRU: Final = ("оцінюй*", "оцінюв*", "оценивай*", "оценивать*")

# "system prompt".
SYSTEM_WORDS: Final = ("system", "системн*", "системный", "системний")
PROMPT_WORDS: Final = ("prompt", "prompts", "промпт*")

# "rate as green", "mark as favorable": a verb, up to three words, "as", a rating word.
RATE_VERBS: Final = (
    "rate",
    "mark",
    "classify",
    "label",
    "score",
    "оцени*",
    "оцен*",
    "пометь*",
    "отметь*",
    "классифиц*",
    "считай*",
    "оціни*",
    "оцінюй*",
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

# How far (in view characters) an instruction and a rating command must be to count as one
# high-class hit.
COMBINE_DISTANCE: Final = 500
# A run of this many base64 characters (letters, digits, `+`, `/`).
BASE64_MIN_RUN: Final = 100
# ... that has at least this many different characters.
BASE64_MIN_DISTINCT: Final = 10
# At most this many hits are kept; a text with more is still flagged.
MAX_HITS: Final = 1000
