# ruff: noqa: RUF001, RUF002 - Cyrillic and look-alike characters are the point of these samples
"""Canary identifiers of every ADR 0008 class, in UK, RU and EN (ADR 0015 point 6).

Everything is synthetic. Checksummed values are computed here with the public
algorithms; they belong to nobody. A ``Canary`` is one sentence with one or more
secret values (``needles``). The harness plants the sentence in every location and
input path, runs the pipeline and looks for the needles in the masked document.

Characters are limited to what the PDF test font can show (ASCII, U+0400..U+045F,
``ґ Ґ « » — – № ’``).
"""

from __future__ import annotations

from dataclasses import dataclass

from tests.pseudo_helpers import CARD_SPACED, IBAN, IBAN_SPACED, edrpou, luhn_card, rnokpp

# ----------------------------------------------------------------- checksum values


def _inn10(nine: str) -> str:
    weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    return nine + str(sum(int(d) * w for d, w in zip(nine, weights, strict=True)) % 11 % 10)


def _inn12(ten: str) -> str:
    w11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    w12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    n11 = ten + str(sum(int(d) * w for d, w in zip(ten, w11, strict=True)) % 11 % 10)
    return n11 + str(sum(int(d) * w for d, w in zip(n11, w12, strict=True)) % 11 % 10)


def _ogrn(twelve: str) -> str:
    return twelve + str(int(twelve) % 11 % 10)


def _snils(nine: str) -> str:
    total = sum(int(d) * w for d, w in zip(nine, range(9, 0, -1), strict=True))
    if total in (100, 101):
        total = 0
    elif total > 101:
        total %= 101
        total = 0 if total == 100 else total
    return f"{nine[:3]}-{nine[3:6]}-{nine[6:]} {total:02d}"


def _iban(country: str, bban: str) -> str:
    digits = "".join(str(int(c, 36)) for c in bban + country + "00")
    return f"{country}{98 - int(digits) % 97:02d}{bban}"


def _spaced(value: str, step: int = 4) -> str:
    return " ".join(value[i : i + step] for i in range(0, len(value), step))


EDRPOU_1 = edrpou("4417719")
EDRPOU_2 = edrpou("3351206")
RNOKPP_1 = rnokpp("291847365")
RNOKPP_2 = rnokpp("318264097")
RNOKPP_3 = rnokpp("276195483")
INN10 = _inn10("771834526")
OGRN = _ogrn("102770054321")
OKPO = edrpou("5560127")
INN12 = _inn12("5047193826")
SNILS = _snils("145872936")
IBAN_2 = _iban("UA", "305299" + "0000026003345678901")  # check digits computed, 29 characters
IBAN_GB = _iban("GB", "OAKM60161331926819")
CARD_2 = luhn_card("510000987654321")
CARD_EN = luhn_card("411122223333444")

ALL_LANGS = ("uk", "ru", "en")


@dataclass(frozen=True)
class Canary:
    id: str
    lang: str  # uk | ru | en
    cls: str  # ADR 0008 class
    text: str  # one sentence; planted as is
    needles: tuple[str, ...]  # secret values; matched case-insensitively, NFKC, skeleton
    only_paths: frozenset[str] | None = None  # variants that need a path feature
    core: bool = False  # also used in the short running header/footer of the PDF


def _c(  # noqa: PLR0913 - positional record builder
    id_: str,
    lang: str,
    cls: str,
    text: str,
    *needles: str,
    only_paths: tuple[str, ...] | None = None,
    core: bool = False,
) -> Canary:
    return Canary(
        id_, lang, cls, text, needles, frozenset(only_paths) if only_paths else None, core
    )


CANARIES: tuple[Canary, ...] = (
    # ------------------------------------------------------------------ PERSON
    _c(
        "uk-person-forms",
        "uk",
        "PERSON",
        "Страхувальник — Мирошниченко Святослав Орестович. Виплату отримує Мирошниченку С.О., "
        "підписав С. О. Мирошниченко.",
        "Мирошниченк",
        core=True,
    ),
    _c(
        "uk-person-double",
        "uk",
        "PERSON",
        "Вигодонабувач — Ткачук-Левицька Марія Богданівна (далі — Вигодонабувач).",
        "Ткачук",
        "Левицьк",
    ),
    _c(
        "uk-person-common-word",
        "uk",
        "PERSON",
        "Страхувальник — Коваль Назар Юрійович, Вигодонабувач — Мельник Леся Йосипівна.",
        "Коваль",
        "Мельник",
    ),
    _c(
        "uk-person-vocative",
        "uk",
        "PERSON",
        "Шановна Ярославо Андріївно, вашу заяву розглянуто.",
        "Ярославо",
        "Андріївно",
    ),
    _c(
        "uk-person-zero-width",
        "uk",
        "PERSON",
        "Страхувальник — Руд\u200bницький Тарас Юрійович (далі — Страхувальник).",
        "Рудницьк",
    ),
    _c(
        "uk-person-soft-hyphen",
        "uk",
        "PERSON",
        "Страхувальник — Левандовсь­кий Остап Григорович (далі — Страхувальник).",
        "Левандовськ",
    ),
    _c(
        "uk-person-line-end-hyphen",
        "uk",
        "PERSON",
        "Страхувальник — Левченко-\nКравець Ілларіон Максимович (далі — Страхувальник).",
        "Левченко",
        "Кравець",
        only_paths=("ocr",),
    ),
    _c(
        "uk-person-homoglyph",
        "uk",
        "PERSON",
        "Страхувальник — Пeтрeнко Ігор Миколайович (далі — Страхувальник).",
        "Петренк",
    ),
    _c(
        "uk-person-translit",
        "uk",
        "PERSON",
        "Страхувальник: PRYTULA Oleksandr Mykolayovych (Притула Олександр Миколайович).",
        "Prytula",
        "Притула",
    ),
    _c(
        "uk-person-signature",
        "uk",
        "SIGNATURE",
        "Страхувальник: ____________ /Бойчук Д.П./",
        "Бойчук",
    ),
    _c(
        "uk-health",
        "uk",
        "HEALTH",
        "Застрахована особа Гончаренко Віра Леонідівна має діагноз гіпертонічна хвороба ІІ стадії.",
        "Гончаренк",
        "гіпертонічна хвороба",
    ),
    _c(
        "ru-person-forms",
        "ru",
        "PERSON",
        "Страхователь: Ковалевский Артём Ильич. Полис выдан Ковалевскому А.И., "
        "подписал А. И. Ковалевский.",
        "Ковалевск",
    ),
    _c(
        "ru-person-double",
        "ru",
        "PERSON",
        "Представитель — Воронцов-Ляшенко Игорь Львович.",
        "Воронцов",
        "Ляшенк",
    ),
    _c(
        "ru-person-ip",
        "ru",
        "ORG",
        "Услуги оказывает индивидуальный предприниматель Захаров Валерий Кузьмич.",
        "Захаров",
    ),
    _c(
        "en-person-forms",
        "en",
        "PERSON",
        "The Customer, represented by Nigel Fairbanks, agrees. Mr N. Fairbanks signs for it.",
        "Fairbanks",
        core=True,
    ),
    _c(
        "en-person-insured",
        "en",
        "PERSON",
        "Insured: Priscilla Harrowgate (the Insured), born in the county of Kent.",
        "Harrowgate",
    ),
    _c(
        "en-signature",
        "en",
        "SIGNATURE",
        "Buyer: ____________ /Alistair Winterbourne/",
        "Winterbourne",
    ),
    _c(
        "ru-signature",
        "ru",
        "SIGNATURE",
        "Арендатор: ____________ /Фёдоров И.П./",
        "Фёдоров",
    ),
    _c(
        "en-health",
        "en",
        "HEALTH",
        "The insured, Gregory Pennington, has been diagnosed with type 2 diabetes.",
        "Pennington",
        "type 2 diabetes",
    ),
    # -------------------------------------------------------------------- ORG
    _c(
        "uk-org-quoted",
        "uk",
        "ORG",
        "ТОВ «Зорепад Інвест», в особі директора Гнатюка Романа Ігоровича, що діє на підставі "
        "Статуту (далі — Страховик).",
        "Зорепад",
        "Гнатюк",
        core=True,
    ),
    _c(
        "uk-org-bank",
        "uk",
        "ORG",
        "Розрахунки проводяться через АТ «Банк Південний Берег» за реквізитами Страховика.",
        "Південний Берег",
    ),
    _c(
        "uk-org-brand",
        "uk",
        "ORG",
        "Страховик пропонує продукт КАСКО «Сузір’я Плюс» на умовах цього договору.",
        "Сузір",
    ),
    _c(
        "uk-org-defined-term",
        "uk",
        "ORG",
        "Компанія ТОВ «Вишневий Дім» (далі — «Вишневий Дім») зобов’язується виплатити "
        "відшкодування.",
        "Вишневий",
    ),
    _c(
        "uk-org-fop",
        "uk",
        "ORG",
        "ФОП Дорошенко Ярема Остапович діє як виконавець за цим договором.",
        "Дорошенк",
    ),
    _c(
        "uk-org-one-word",
        "uk",
        "ORG",
        "Послуги з ремонту надає Теплобуд відповідно до умов договору.",
        "Теплобуд",
    ),
    _c(
        "ru-org-quoted",
        "ru",
        "ORG",
        "ООО «Липовый Мёд Трейд», в лице генерального директора Сидорчука Анатолия Павловича, "
        "действующего на основании Устава (далее — Арендодатель).",
        "Липовый",
        "Сидорчук",
    ),
    _c(
        "en-org-ltd",
        "en",
        "ORG",
        "This Agreement is made between Brightwater Holdings Ltd. (the Supplier) and "
        "Oakmont Trading LLC (the Buyer).",
        "Brightwater",
        "Oakmont",
    ),
    _c(
        "en-org-one-word",
        "en",
        "ORG",
        "The goods are supplied by Kestrelworks under this Agreement.",
        "Kestrelworks",
    ),
    # ----------------------------------------------------------------- TAX_ID
    _c(
        "uk-tax-edrpou",
        "uk",
        "TAX_ID",
        f"Страхувальник (код за ЄДРПОУ {EDRPOU_1}) та Страховик (код ЄДРПОУ {EDRPOU_2}) "
        "уклали цей договір.",
        EDRPOU_1,
        EDRPOU_2,
        core=True,
    ),
    _c(
        "uk-tax-rnokpp",
        "uk",
        "TAX_ID",
        f"РНОКПП (ІПН) Страхувальника: {RNOKPP_1}.",
        RNOKPP_1,
    ),
    _c(
        "uk-tax-rnokpp-spaced-keyword",
        "uk",
        "TAX_ID",
        f"РНОКПП Виконавця: {RNOKPP_2[:5]} {RNOKPP_2[5:]}.",
        RNOKPP_2,
    ),
    _c(
        "uk-tax-rnokpp-spaced-after-address",
        "uk",
        "TAX_ID",
        "Страхувальник проживає за адресою: м. Львів, вул. Зелена, буд. 8, кв. 2. "
        f"Також {RNOKPP_3[:5]} {RNOKPP_3[5:]}.",
        RNOKPP_3,
    ),
    _c(
        "uk-tax-unzr",
        "uk",
        "TAX_ID",
        "УНЗР 19910722-54321 вказано у документі.",
        "19910722-54321",
    ),
    _c(
        "ru-tax-legal",
        "ru",
        "TAX_ID",
        f"ИНН {INN10}, КПП 771801001, ОГРН {OGRN}, ОКПО {OKPO}.",
        INN10,
        "771801001",
        OGRN,
        OKPO,
    ),
    _c(
        "ru-tax-person",
        "ru",
        "TAX_ID",
        f"ИНН физического лица {INN12}, СНИЛС {SNILS}.",
        INN12,
        SNILS,
    ),
    _c(
        "en-tax-vat",
        "en",
        "TAX_ID",
        "The Supplier VAT number is DE381472905 and it is shown on every invoice.",
        "DE381472905",
    ),
    # ---------------------------------------------------------------- ACCOUNT
    _c(
        "uk-account-iban",
        "uk",
        "ACCOUNT",
        f"Рахунок Страховика: IBAN {IBAN}, інший рахунок {IBAN_2}, з пробілами {IBAN_SPACED}.",
        IBAN,
        IBAN_2,
        core=True,
    ),
    _c(
        "uk-account-card-mfo",
        "uk",
        "ACCOUNT",
        f"Картка {CARD_SPACED}, МФО 305299, SWIFT KRPLUA2XXXX.",
        CARD_SPACED,
        "KRPLUA2XXXX",
    ),
    _c(
        "uk-account-number",
        "uk",
        "ACCOUNT",
        "Поточний рахунок № 26007123456789 відкрито у банку Страховика.",
        "26007123456789",
    ),
    _c(
        "ru-account",
        "ru",
        "ACCOUNT",
        "Расчётный счёт р/с 40702810400000123456, БИК 045500321.",
        "40702810400000123456",
        "045500321",
    ),
    _c(
        "en-account",
        "en",
        "ACCOUNT",
        f"Payment shall be made to IBAN {_spaced(IBAN_GB)}, card {_spaced(CARD_EN)}.",
        IBAN_GB,
        CARD_EN,
    ),
    # --------------------------------------------------- PHONE / EMAIL / URL
    _c(
        "uk-email",
        "uk",
        "EMAIL",
        "Електронна пошта: oksana.synytsia@example.com, обфускована: "
        "office(at)synytsia-mail.com.ua.",
        "synytsia",
        core=True,
    ),
    _c(
        "uk-phone",
        "uk",
        "PHONE",
        "Телефони: +380 67 555 41 82 та (048) 777-33-19.",
        "380675554182",
        "0487773319",
    ),
    _c(
        "uk-url",
        "uk",
        "URL",
        "Сайт: https://www.zorepad-claims.com.ua/claims, також zorepad-partner.com.ua "
        "і @zorepad_support_bot.",
        "zorepad-claims",
        "zorepad-partner",
        "zorepad_support_bot",
    ),
    _c(
        "ru-contacts",
        "ru",
        "EMAIL",
        "Тел.: +7 (495) 555-48-26, e-mail: sidorchuk.lm@example-lease.ru, "
        "сайт www.lipovy-trade.ru.",
        "74955554826",
        "sidorchuk.lm",
        "lipovy-trade",
    ),
    _c(
        "en-contacts",
        "en",
        "EMAIL",
        "Contact: Tel +44 20 7946 0731, mail nigel.fairbanks(at)brightwater-hq.example, "
        "web https://brightwater-hq.example/help.",
        "442079460731",
        "nigel.fairbanks",
        "brightwater-hq",
    ),
    # ---------------------------------------------------------------- ADDRESS
    _c(
        "uk-address",
        "uk",
        "ADDRESS",
        "Предмет страхування — квартира за адресою: м. Одеса, вул. Каштанова, буд. 17, кв. 52.",
        "Каштанова",
    ),
    _c(
        "uk-cadastral",
        "uk",
        "ADDRESS",
        "Кадастровий номер земельної ділянки 5110136900:02:004:0371.",
        "5110136900:02:004:0371",
    ),
    _c(
        "ru-address",
        "ru",
        "ADDRESS",
        "Помещение находится по адресу: г. Днепр, ул. Сиреневая, д. 41, офис 12.",
        "Сиреневая",
    ),
    _c(
        "en-address",
        "en",
        "ADDRESS",
        "The registered office of the Supplier is at 221 Larkspur Lane, Springfield, IL 62704.",
        "Larkspur",
    ),
    # ---------------------------------------------------------- PERSONAL_DOC
    _c(
        "uk-personal-doc",
        "uk",
        "PERSONAL_DOC",
        "Паспорт: серія КН № 482915; дата народження 09.11.1987.",
        "482915",
        "09.11.1987",
    ),
    _c(
        "ru-personal-doc",
        "ru",
        "PERSONAL_DOC",
        "Паспорт серия 4510 № 123987, дата рождения 21.06.1979.",
        "123987",
        "21.06.1979",
    ),
    _c(
        "en-personal-doc",
        "en",
        "PERSONAL_DOC",
        "Passport No. 531847260, date of birth 04/17/1982.",
        "531847260",
        "04/17/1982",
    ),
    # ----------------------------------------------------------------- DOC_NO
    _c(
        "uk-doc-no",
        "uk",
        "DOC_NO",
        "Договір страхування № ПС-2031/0988 від 12.01.2031, справа № 916/7734/31.",
        "ПС-2031/0988",
        "916/7734/31",
    ),
    _c(
        "ru-doc-no",
        "ru",
        "DOC_NO",
        "Договор аренды № 15-К/2031 от 01.03.2031, дело № А40-123456/31.",
        "15-К/2031",
        "А40-123456/31",
    ),
    _c(
        "en-doc-no",
        "en",
        "DOC_NO",
        "Policy No. HX-7741-2031-B and Case No. 2031-CV-004417 apply to this claim.",
        "HX-7741-2031-B",
        "2031-CV-004417",
    ),
    # ---------------------------------------------------------------- VEHICLE
    _c(
        "uk-vehicle",
        "uk",
        "VEHICLE",
        "Автомобіль: VIN WVWZZZ3CZ9E778811, державний номер КА 7788 ОР, "
        "свідоцтво про реєстрацію ТХК 554433.",
        "WVWZZZ3CZ9E778811",
        "КА 7788 ОР",
        "ТХК 554433",
    ),
    _c(
        "ru-vehicle",
        "ru",
        "VEHICLE",
        "Автомобиль, VIN XTA210930Y7712345, госномер Е123КХ 77, ПТС 77 ТТ 654321.",
        "XTA210930Y7712345",
        "Е123КХ 77",
        "77 ТТ 654321",
    ),
    _c(
        "en-vehicle",
        "en",
        "VEHICLE",
        "Vehicle VIN 2T1BR32E55C778899, registration plate KDL 4471.",
        "2T1BR32E55C778899",
        "KDL 4471",
    ),
    # -------------------------------------------------------------- SIGNATURE
    _c(
        "uk-kep",
        "uk",
        "SIGNATURE",
        "Підписано КЕП, серійний номер сертифіката 5A3F9C2B77E10D44.",
        "5A3F9C2B77E10D44",
    ),
)

BY_ID = {c.id: c for c in CANARIES}
assert len(BY_ID) == len(CANARIES), "duplicate canary id"

CLASSES = frozenset(c.cls for c in CANARIES)
