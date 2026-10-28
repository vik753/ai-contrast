# ruff: noqa: RUF001, PT018
"""S5b-T1 unit tests of the detector parts (matching view, checksums, stems, tables)."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.pseudo import checksums, tables
from app.pseudo.lexicon import DETECTOR_VERSION, is_patronymic, is_role, stem_key
from app.pseudo.matching import build_view, fold
from tests.helpers import all_log_text
from tests.pseudo_helpers import detect

BACKEND = Path(__file__).resolve().parents[1]
Make = Callable[..., TestClient]


def test_confusable_table_matches_the_generator_output() -> None:
    result = subprocess.run(  # noqa: S603 - fixed arguments, our own script
        [sys.executable, str(BACKEND / "scripts" / "gen_confusable_table.py"), "--check"],
        capture_output=True,
        check=False,
        cwd=BACKEND,
    )

    assert result.returncode == 0, result.stderr


def test_version_is_a_stable_short_identifier() -> None:
    assert re.fullmatch(r"pseudo-[0-9a-f]{16}", DETECTOR_VERSION)


# ----------------------------------------------------------------- matching view


def test_view_without_changes_is_the_identity() -> None:
    view = build_view(["abc def", "ghi"])

    assert view.src is None
    assert view.u == "abc def\nghi"
    assert view.spans(4, 7) == [(0, 4, 7)]


def test_view_match_across_a_block_boundary_is_split_per_block() -> None:
    view = build_view(["abc def", "ghi"])

    assert view.spans(4, 11) == [(0, 4, 7), (1, 0, 3)]


def test_view_expanded_character_is_snapped_outward_on_both_sides() -> None:
    view = build_view(["x№y"])  # "№" becomes "No"

    assert view.u == "xNoy"
    assert view.spans(1, 2) == [(0, 1, 2)]  # only "N": the whole source character
    assert view.spans(2, 3) == [(0, 1, 2)]  # only "o": the same source character
    assert view.spans(2, 4) == [(0, 1, 3)]


def test_view_line_end_hyphen_is_removed_and_the_span_covers_it() -> None:
    view = build_view(["Іва-\nненко", "тест-\nу Б"])

    assert view.u.startswith("Іваненко")
    assert view.spans(0, 8) == [(0, 0, 10)]


def test_view_hyphen_before_an_upper_case_letter_is_kept() -> None:
    view = build_view(["ab-\nCd"])

    assert view.u == "ab-\nCd"


def test_view_hyphen_at_block_end_joins_the_next_block() -> None:
    view = build_view(["Аль-", "фа Тест"])

    assert view.u == "Альфа Тест"
    assert view.spans(0, 10) == [(0, 0, 4), (1, 0, 7)]


def test_fold_maps_cyrillic_and_greek_look_alikes_to_latin_and_ignores_case() -> None:
    assert fold("ІВАН") == fold("IBAH") == fold("iван")
    assert fold("Ρоѕ") == fold("Pos")  # Greek rho, Cyrillic o and dze


def test_fold_keeps_the_length() -> None:
    text = "İß ﬁ№ abc"
    assert len(fold(text)) == len(__import__("unicodedata").normalize("NFKC", text))


# --------------------------------------------------------------------- checksums


@pytest.mark.parametrize("value", ["21045679", "38126404", "64001830", "10000062"])
def test_checksum_edrpou_valid(value: str) -> None:
    assert checksums.edrpou_valid(value)
    assert not checksums.edrpou_valid(value[:7] + str((int(value[7]) + 1) % 10))


def test_checksum_other_codes() -> None:
    assert checksums.rnokpp_valid("3012345670")
    assert checksums.inn10_valid("7712345671")
    assert checksums.inn12_valid("504712345623")
    assert checksums.ogrn_valid("1027700123450")
    assert checksums.ogrnip_valid("316774600012348")
    assert checksums.snils_valid("11223344595")
    assert checksums.luhn_valid("4111111111111111")
    assert checksums.iban_valid("GB82WEST12345698765432")
    assert not checksums.iban_valid("GB82WEST12345698765433")
    assert not checksums.luhn_valid("4111111111111112")


# ------------------------------------------------------------------------ stems


@pytest.mark.parametrize(
    ("forms", "stem"),
    [
        (["Шевченко", "Шевченка", "Шевченку", "Шевченком"], "shevchenk"),
        (["Сидоров", "Сидорова", "Сидорову", "Сидоровым", "Сидоровой"], "sidorov"),
        (["Іваненко", "Ivanenko", "IVANENKO", "Iванeнко"], "ivanenk"),
        (["Мельник", "Мельника", "Мельнику", "Melnyk"], "melnik"),
    ],
)
def test_stem_key_is_equal_for_case_forms_and_spellings(forms: list[str], stem: str) -> None:
    assert {stem_key(form) for form in forms} == {stem}


def test_stem_key_of_different_surnames_differs() -> None:
    assert stem_key("Мельник") != stem_key("Мельниченко")


@pytest.mark.parametrize(
    "word", ["Олексійович", "Миколайовича", "Петрівно", "Іванівна", "Petrovych", "Ивановне"]
)
def test_patronymic_forms_are_recognised(word: str) -> None:
    assert is_patronymic(word)


@pytest.mark.parametrize("word", ["Київ", "Договір", "Мельник", "Rose", "Страховик"])
def test_patronymic_is_not_a_surname_or_a_common_word(word: str) -> None:
    assert not is_patronymic(word)


def test_role_words_match_case_forms_only_by_prefix() -> None:
    assert is_role(fold("Страховика")) and is_role(fold("Buyer")) and is_role(fold("Орендарю"))
    assert not is_role(fold("Іваненко"))


def test_tables_have_no_empty_entry() -> None:
    for name in dir(tables):
        value = getattr(tables, name)
        if name.isupper() and isinstance(value, tuple):
            assert all(item for item in value), name


# -------------------------------------------------------------------- behaviour


def test_log_line_has_counts_per_class_and_no_value(
    make_client: Make, log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    detect(client, "Пишіть на secret.person@example.com або +380 44 123 45 67.")

    text = all_log_text(log_capture)
    assert "EMAIL:1" in text and "PHONE:1" in text
    assert "secret.person" not in text and "123 45 67" not in text


def test_requisites_heading_capitals_with_colon_do_not_end_the_section(make_client: Make) -> None:
    data = detect(make_client(), "1. Текст.", "Реквізити та підписи сторін", "IBAN: ABC", "ТОВ: 5")

    kinds = [c["section_kind"] for c in data["clauses"]]
    assert kinds == [None, "requisites"]


def test_annex_heading_in_capitals_still_ends_the_requisites_section(make_client: Make) -> None:
    data = detect(make_client(), "1. Текст.", "Реквізити та підписи сторін", "ДОДАТОК 1")

    assert [c["section_kind"] for c in data["clauses"]] == [None, "requisites", None]


def test_spans_of_an_entity_split_across_blocks_stay_inside_their_blocks(make_client: Make) -> None:
    data = detect(make_client(), "Страхова компанія ТОВ «Аль-", "фа Тест» надає послуги.")

    [entity] = [e for e in data["entities"] if e["class"] == "ORG"]
    for block, start, end in entity["spans"]:
        assert 0 <= start < end <= len(data["blocks"][block]["text"])


def test_two_blocks_hold_one_value_each_grouped_across_case_and_form(make_client: Make) -> None:
    data = detect(make_client(), "Пишіть на Ivan@Example.com.", "Копія: ivan@example.com.")

    assert len([e for e in data["entities"] if e["class"] == "EMAIL"]) == 1
