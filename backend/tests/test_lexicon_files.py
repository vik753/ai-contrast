"""S9-T0: shape of the checked-in lexicons in ``shared/lexicon/`` (data only)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEXICON = ROOT / "shared" / "lexicon"
CATALOG = ROOT / "shared" / "topics"
LANGS = ("en", "uk", "ru")
FILES = (
    "exception_markers",
    "global_override_markers",
    "clause_references",
    "relative_references",
    "unit_words",
    "number_words",
    "sentence_abbreviations",
)


def _load(name: str) -> dict[str, Any]:
    data = json.loads((LEXICON / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _lists(name: str) -> Iterator[tuple[str, list[str]]]:
    """Every word list of a file as ``(path, list)``."""
    data = _load(name)
    for lang in LANGS:
        if name in {"exception_markers", "global_override_markers", "relative_references"}:
            yield f"{name}.{lang}", data[lang]
        elif name == "clause_references":
            for key in ("prefixes", "joiners", "range_words", "self_reference"):
                yield f"{name}.{key}.{lang}", data[key][lang]
        elif name == "unit_words":
            yield f"{name}.percent_marks.{lang}", data["percent_marks"][lang]
            for unit, words in data["units"].items():
                yield f"{name}.{unit}.{lang}", words[lang]
        elif name == "number_words":
            for number, words in data[lang].items():
                yield f"{name}.{lang}.{number}", words
        elif name == "sentence_abbreviations":
            yield f"{name}.never_end.{lang}", data["never_end"][lang]
            yield f"{name}.may_end.{lang}", data["may_end"][lang]


@pytest.mark.parametrize("name", FILES)
def test_lexicon_file_has_a_version(name: str) -> None:
    version = _load(name)["version"]

    assert isinstance(version, int)
    assert not isinstance(version, bool)
    assert version >= 1


@pytest.mark.parametrize("name", FILES)
def test_lexicon_file_has_all_three_languages(name: str) -> None:
    data = _load(name)

    flat = {"exception_markers", "global_override_markers", "relative_references", "number_words"}
    if name in flat:
        assert all(lang in data for lang in LANGS)
    elif name == "clause_references":
        keys = ("prefixes", "joiners", "range_words", "self_reference")
        assert all(lang in data[key] for key in keys for lang in LANGS)
    elif name == "unit_words":
        assert all(lang in data["percent_marks"] for lang in LANGS)
        assert all(lang in words for words in data["units"].values() for lang in LANGS)
    else:
        assert all(lang in data[key] for key in ("never_end", "may_end") for lang in LANGS)


@pytest.mark.parametrize("name", FILES)
def test_lexicon_lists_are_not_empty_and_hold_clean_strings(name: str) -> None:
    seen = 0
    for path, words in _lists(name):
        seen += 1
        assert isinstance(words, list), path
        assert words, path
        for word in words:
            assert isinstance(word, str), path
            assert word.strip() == word, path
            assert word, path
    assert seen >= 3


@pytest.mark.parametrize("name", FILES)
def test_lexicon_lists_have_no_duplicates_after_casefold(name: str) -> None:
    for path, words in _lists(name):
        folded = [w.casefold() for w in words]
        assert len(set(folded)) == len(folded), path


@pytest.mark.parametrize("name", ["exception_markers", "global_override_markers"])
def test_lexicon_added_in_review_entries_are_in_the_main_lists(name: str) -> None:
    data = _load(name)

    for lang in LANGS:
        assert set(data["added_in_review"][lang]) <= set(data[lang]), f"{name}.{lang}"


def test_lexicon_abbreviations_never_end_and_may_end_do_not_overlap() -> None:
    data = _load("sentence_abbreviations")

    for lang in LANGS:
        assert not set(data["never_end"][lang]) & set(data["may_end"][lang]), lang


def test_lexicon_abbreviations_end_with_a_dot() -> None:
    data = _load("sentence_abbreviations")

    for key in ("never_end", "may_end"):
        for lang in LANGS:
            assert all(word.endswith(".") for word in data[key][lang]), f"{key}.{lang}"


def test_lexicon_number_words_cover_atoms_zero_to_nineteen_tens_and_hundreds() -> None:
    data = _load("number_words")
    numbers = [*range(0, 20), *range(20, 100, 10), *range(100, 1000, 100), 1000]
    required = [str(n) for n in numbers]

    for lang in LANGS:
        missing = [n for n in required if n not in data[lang]]
        assert not missing, f"{lang}: {missing}"


def test_lexicon_number_words_keys_are_numbers() -> None:
    data = _load("number_words")

    for lang in LANGS:
        for key in data[lang]:
            float(key)


def _catalog_units() -> set[str]:
    units: set[str] = set()
    for path in sorted(CATALOG.glob("*.json")):
        domain = json.loads(path.read_text(encoding="utf-8"))
        for topic in domain["topics"]:
            for attribute in topic["attributes"]:
                units.update(attribute.get("units") or [])
    return units


def test_lexicon_unit_words_cover_every_catalog_unit() -> None:
    catalog_units = _catalog_units()
    covered = set(_load("unit_words")["units"])

    assert catalog_units, "the catalog must declare units"
    assert catalog_units <= covered, sorted(catalog_units - covered)


def test_lexicon_unit_words_have_no_unit_unknown_to_the_catalog_model() -> None:
    expected = {
        "UAH",
        "USD",
        "EUR",
        "percent_of_sum",
        "percent_of_loss",
        "days",
        "working_days",
        "months",
        "years",
        "hours",
    }

    assert set(_load("unit_words")["units"]) == expected
