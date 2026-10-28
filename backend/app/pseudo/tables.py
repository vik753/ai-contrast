# ruff: noqa: RUF001, RUF002, RUF003
"""Checked-in tables of the detector (ADR 0008 point 1, ADR 0015 point 2).

Raw, human-readable values. ``app.pseudo.lexicon`` folds them with the same skeleton the
detector applies to the text (NFKC, confusable skeleton, lower case), so a table entry
matches its homoglyph variants. Changing any value changes ``DETECTOR_VERSION``.

A "run" is a maximal sequence of letters and digits; ``р/с`` is the two runs ``р``, ``с``.
Multi-run keywords are tuples of runs.
"""

from __future__ import annotations

from typing import Final

# --- legal forms ---------------------------------------------------------------------
# Followed by a name (quoted or not). Case is significant; the upper-case variant is
# accepted as well.
LEGAL_FORMS_PREFIX: Final = (
    "ТОВ", "ТзОВ", "ТДВ", "ПрАТ", "ПАТ", "АТ", "ПП", "КП", "ДП", "ОСББ", "ОСМД",
    "ГО", "КФГ", "ФГ", "ООО", "ЗАО", "ОАО", "АО", "ПАО", "НКО", "МУП",
    "ГУП", "ТСЖ", "ЧП", "LLC", "LLP", "Ltd", "Inc", "Corp", "GmbH", "PLC", "Limited",
)  # fmt: skip
# Follow a name written in Latin letters ("Northwind Logistics Ltd.").
LEGAL_FORMS_SUFFIX: Final = (
    "Ltd", "Inc", "LLC", "LLP", "GmbH", "AG", "PLC", "Corp", "SA", "BV", "NV", "Limited",
    "Pty", "OOO", "TOV",
)  # fmt: skip
# Sole proprietors: ORG (form and name) and PERSON (name only).
SOLE_TRADER_FORMS: Final = ("ФОП", "ФЛП", "ІП", "ИП")
# A quoted name after one of these words (or after an all-capitals word) is an ORG.
ORG_NOUNS: Final = (
    "компанія", "компанії", "компанію", "компанією", "компания", "компании", "company",
    "банк", "банку", "банка", "bank", "підприємство", "предприятие", "фірма", "фирма",
    "корпорація", "корпорация", "товариство", "общество", "організація", "организация",
    "організації", "організацію",
)  # fmt: skip

# --- context keywords ----------------------------------------------------------------
# kind -> keywords; a keyword is a run or a tuple of runs.
CONTEXT: Final[dict[str, tuple[str | tuple[str, ...], ...]]] = {
    "tax": (
        "єдрпоу",
        "едрпоу",
        "edrpou",
        "окпо",
        "okpo",
        "іпн",
        "ipn",
        "рнокпп",
        "рнокпп",
        "інн",
        "инн",
        "inn",
        "огрн",
        "ogrn",
        "огрнип",
        "снилс",
        "snils",
        "кпп",
        "kpp",
        "vat",
        "tin",
        "ein",
        "унзр",
        "податковий",
        "податкова",
        "налоговый",
        "налоговая",
        "tax",
        ("ідентифікаційний", "код"),
        ("идентификационный", "номер"),
    ),
    "kpp": ("кпп", "kpp"),
    "unzr": ("унзр", "unzr"),
    "snils": ("снилс", "snils"),
    "vat": ("vat", "ндс", "пдв"),
    "ein": ("tax", "ein", "tin", "податковий", "налоговый"),
    "iban": ("iban",),
    "swift": ("swift", "bic"),
    "mfo": ("мфо", "mfo"),
    "bik": ("бик", "bik"),
    "account": (
        "рахунок",
        "рахунку",
        "рахунка",
        "рахунки",
        "счет",
        "счета",
        "счету",
        "account",
        "acct",
        "розрахунковий",
        "расчетный",
        ("р", "с"),
        ("к", "с"),
        ("р", "сч"),
        "корр",
        "кореспондентський",
    ),
    "card": (
        "картка",
        "картки",
        "картку",
        "карткою",
        "карта",
        "карты",
        "карту",
        "картой",
        "card",
        "cards",
    ),
    "phone": (
        "тел",
        "телефон",
        "телефони",
        "телефону",
        "моб",
        "мобільний",
        "мобильный",
        "tel",
        "phone",
        "mobile",
        "факс",
        "fax",
        "whatsapp",
        "viber",
        "telegram",
    ),
    "passport": ("паспорт", "паспорта", "passport"),
    "idcard": (
        ("id", "картка"),
        ("id", "картки"),
        ("id", "карта"),
        ("id", "card"),
        ("id", "картку"),
    ),
    "driver": (
        ("посвідчення", "водія"),
        ("водійське", "посвідчення"),
        ("водительское", "удостоверение"),
        ("driver", "licence"),
        ("driver", "license"),
        ("driving", "licence"),
        ("driving", "license"),
    ),
    "dob": (
        ("дата", "народження"),
        ("дата", "рождения"),
        ("date", "of", "birth"),
        "народився",
        "народилася",
        "родился",
        "родилась",
        "born",
    ),
    "regcert": (
        "птс",
        ("свідоцтво", "про", "реєстрацію"),
        ("свидетельство", "о", "регистрации"),
        ("registration", "certificate"),
        "техпаспорт",
    ),
    "address": (
        "адреса",
        "адресою",
        "адресу",
        "адресі",
        "адреси",
        "адрес",
        "адресе",
        "address",
        "місцезнаходження",
        "местонахождение",
        "прописки",
    ),
    "health": ("діагноз", "диагноз", "diagnosis"),
    "serial": (
        ("серійний", "номер", "сертифіката"),
        ("серийный", "номер", "сертификата"),
        ("certificate", "serial", "number"),
        ("серійний", "номер"),
        ("serial", "number"),
    ),
    "email": ("email", ("e", "mail"), "mail", "пошта", "пошту", "почта", "пошти"),
}
# A document word before "№" turns the number into a DOC_NO. Prefix match, up to six more
# letters (case endings).
DOCUMENT_WORDS: Final = (
    "договір", "договор", "контракт", "угода", "угоди", "поліс", "полис", "довіреність",
    "доверенность", "рахунок", "рахунку", "счет", "інвойс", "invoice", "ліцензія", "ліцензії",
    "лицензия", "справа", "справі", "дело", "наказ", "приказ", "акт", "додаток", "додатку",
    "приложение", "протокол", "свідоцтво", "сертифікат", "certificate", "contract",
    "agreement", "policy", "license", "licence", "case", "order", "annex", "appendix",
    "receipt", "claim", "заява", "заявка", "накладна", "видаткова", "доручення", "постанова",
    "рішення", "ухвала", "специфікація", "спецификация", "specification", "quote", "offer",
)  # fmt: skip

# --- roles, titles and other words that are not names --------------------------------
# Prefix match with up to four more letters (case endings).
ROLE_WORDS: Final = (
    "страховик", "страхувальник", "вигодонабувач", "замовник", "виконавець", "виконавц",
    "покупець", "покупц", "продавець", "продавц", "орендар", "орендодав", "наймач",
    "наймодав", "позичальник", "позикодав", "кредитор", "боржник", "перевізник",
    "відправник", "одержувач", "постачальник", "підрядник", "клієнт", "поручител",
    "гарант", "принципал", "страховщик", "страхователь", "страхователя", "выгодоприобретател",
    "заказчик", "исполнител", "покупател", "арендатор", "арендодател", "наниматель",
    "заемщик", "займодавец", "должник", "перевозчик", "отправитель", "получатель",
    "поставщик", "подрядчик", "клиент", "поручитель", "buyer", "seller", "insurer",
    "insured", "customer", "supplier", "client", "lessor", "lessee", "tenant", "landlord",
    "contractor", "carrier", "borrower", "lender", "guarantor", "party", "parties",
    "beneficiary", "policyholder", "company", "agent", "vendor", "purchaser", "employer",
    "employee", "licensor", "licensee", "consultant", "provider", "сторона", "сторони",
    "сторін", "сторона", "стороны", "сторон", "договір", "договор", "agreement", "contract",
    "директор", "director", "бухгалтер", "accountant", "manager", "менеджер",
    "представник", "представитель", "representative", "підписант", "signatory",
    "страхов", "застрахован", "insurance",
)  # fmt: skip
# Words that start a sentence or a list item and are not names (exact, folded).
NOT_NAMES: Final = (
    "шановна", "шановний", "шановні", "вельмишановний", "вельмишановна", "dear",
    "уважаемый", "уважаемая", "уважаемые", "громадянин", "громадянка", "гражданин",
    "гражданка", "пан", "пані", "mr", "mrs", "ms", "dr", "статут", "статуту", "устав",
    "устава", "charter", "закон", "закону", "кодекс", "кодексу", "україна", "україни",
    "украина", "ukraine", "додаток", "приложение", "annex", "розділ", "стаття", "пункт",
    "article", "section", "clause", "date", "дата", "сума", "предмет", "термін", "строк",
    "територія", "територия", "territory", "правила", "правил", "умови", "условия",
    "terms", "підпис", "подпись", "signature", "печатка", "stamp", "відповідальність",
    "ответственность", "liability", "оплата", "payment", "insured", "notice", "notices",
    "contact", "contacts", "контакт", "контакти", "місто", "город", "city", "область",
    "oblast", "район", "примітка", "примечание", "note", "see", "див", "виплата", "премія",
    "франшиза", "неустойка", "штраф", "penalty", "тел", "tel", "email", "mail", "сайт",
    "web", "site", "this", "these", "the", "that", "each", "any", "such", "if", "all",
)  # fmt: skip
# Words between a trigger ("в особі") and the name that are skipped (prefix match).
TITLE_WORDS: Final = (
    "директор", "генеральн", "виконавч", "голов", "президент", "керівник", "керуюч",
    "уповноважен", "представник", "засновник", "власник", "заступник", "its", "his",
    "her", "director", "manager", "president", "chairman", "chief", "executive", "officer",
    "representative", "authori", "signatory", "owner", "founder", "head", "ceo", "cfo",
    "руководител", "генеральный", "уполномоченн", "учредитель", "владелец", "громадянин",
    "громадянк", "гражданин", "гражданк", "пан", "пані", "mr", "mrs", "ms", "dr", "sir",
    "фізичн", "особ", "физическ", "лиц",
)  # fmt: skip
# Triggers before a representative's name (runs).
PERSON_TRIGGERS: Final = (
    ("в", "особі"), ("в", "лице"), ("represented", "by"), ("acting", "through"),
    ("громадянин",), ("громадянка",), ("гражданин",), ("гражданка",), ("пан",), ("пані",),
    ("mr",), ("mrs",), ("ms",), ("dr",),
)  # fmt: skip
# Opens a definition: (далі — X), (the "X"). Runs.
DEFINITION_OPENERS: Final = (
    ("далі",), ("далее",), ("hereinafter",), ("the",), ("надалі",), ("в", "подальшому"),
    ("в", "дальнейшем"),
)  # fmt: skip
# Words of the definition opener that follow the first one ("далі за текстом").
DEFINITION_FILLERS: Final = ("за", "текстом", "по", "тексту", "referred", "to", "as", "also")

# --- obligation markers, requisites labels --------------------------------------------
# A requisites line with one of these (folded runs) is always kept.
OBLIGATION_MARKERS: Final = (
    "зобов", "обов", "відмовляється", "відмовляються", "погоджується", "погоджуються",
    "право", "обязуется", "обязан", "обязуются", "отказывается", "соглашается", "вправе",
    "agrees", "agree", "shall", "must", "undertakes", "waives", "liable", "responsible",
    "відповідає", "відповідальний", "отвечает", "несет", "сплачує", "оплачивает", "pays",
    "may", "will", "should", "не", "not", "no",
)  # fmt: skip
# Closed list of labels of requisites lines (folded runs).
REQUISITES_LABELS: Final = (
    "єдрпоу", "едрпоу", "edrpou", "окпо", "okpo", "іпн", "ipn", "рнокпп", "інн", "инн",
    "inn", "огрн", "огрнип", "снилс", "кпп", "kpp", "vat", "tin", "ein", "унзр", "iban",
    "swift", "bic", "бик", "мфо", "mfo", "адреса", "адрес", "address", "юридична",
    "юридическая", "юридичний", "юридический", "поштова", "почтовая", "фактична",
    "фактическая", "registered", "legal", "тел", "телефон", "phone", "tel", "mobile", "факс",
    "fax", "email", "mail", "пошта", "почта", "сайт", "site", "web", "website", "рахунок",
    "счет", "account", "р", "с", "сч", "к", "банк", "bank", "код", "номер", "no", "tax",
    "id", "reg", "registration", "number", "code", "підпис", "подпись", "signature",
    "signatory", "authorised", "authorized", "печатка", "stamp", "м", "п", "mp", "name",
    "найменування", "наименование", "керівник", "руководитель", "дата", "date",
    "посада", "должность", "position", "title", "ім", "я", "фіо", "піб", "фио",
    "банківський", "банковский", "банківські", "банковские", "реквізити", "реквизиты",
    "банківські", "розрахунковий", "расчетный", "кореспондентський", "корреспондентский",
)  # fmt: skip
# Role words in requisites lines: ROLE_WORDS above.

# --- amounts -----------------------------------------------------------------------------
# A number next to one of these (folded, exact) is an amount, a measure or a term.
AMOUNT_WORDS: Final = (
    "грн", "гривня", "гривні", "гривень", "гривну", "uah", "usd", "eur", "rub", "gbp", "pln",
    "chf", "руб", "рублей", "рубля", "рубль", "рублі", "долар", "доларів", "доларов", "долл",
    "євро", "euro", "dollars", "dollar", "euros", "злотих", "коп", "копійок", "копеек", "cents",
    "відсотків", "відсотки", "процентів", "процент", "процентов", "percent", "днів", "дні",
    "день", "дней", "дня", "days", "day", "місяців", "місяці", "місяць", "міс", "месяцев",
    "месяца", "months", "month", "років", "рік", "роки", "года", "год", "лет", "years",
    "year", "годин", "години", "часов", "hours", "hour", "кг", "kg", "км", "km", "кв", "м2",
    "m2", "шт", "pcs", "тонн", "тонни", "тон", "куб", "м3", "m3", "л", "мм", "см", "mm", "cm",
    "робочих", "рабочих", "календарних", "календарных", "working", "calendar", "банківських",
    "банковских", "banking", "тис", "млн", "млрд", "k", "mln",
)  # fmt: skip
CURRENCY_SIGNS: Final = "$€£₴₽¥%"

# --- addresses ---------------------------------------------------------------------------
# Abbreviations whose final full stop does not end a sentence (folded).
ADDRESS_ABBREVIATIONS: Final = (
    "м", "вул", "ул", "г", "пр", "просп", "пров", "бул", "пл", "буд", "д", "кв", "оф", "офіс",
    "с", "смт", "обл", "р", "ст", "st", "ave", "rd", "blvd", "no", "apt", "fl", "bldg", "пер",
    "наб", "ш", "к", "корп", "літ", "під", "пом", "тел", "ід", "стр", "помещ", "комн", "п",
)  # fmt: skip
# First word after an address keyword that starts an address when there is no colon.
ADDRESS_STARTS: Final = ("м", "г", "вул", "ул", "пр", "просп", "бул", "пров", "смт", "с")

# --- name endings ------------------------------------------------------------------------
# Patronymics (folded, lower case; any case form is matched by suffix).
PATRONYMIC_ENDINGS: Final = (
    "ович", "евич", "йович", "ьович", "овича", "евича", "йовича", "ьовича", "овичу", "евичу",
    "йовичу", "ьовичу", "овичем", "евичем", "йовичем", "ьовичем", "овиче", "евиче", "йовиче",
    "ьовиче", "івна", "ївна", "овна", "евна", "ична", "инична", "івни", "ївни", "овны", "евны",
    "ічни", "івні", "ївні", "овне", "евне", "івну", "ївну", "овну", "евну", "івною", "ївною",
    "овной", "евной", "івно", "ївно", "овно", "евно", "ичны", "ичне", "ичну", "ичной",
    "ovych", "ovich", "evych", "evich", "yovych", "ivna", "ovna", "evna", "yivna", "ievna",
    "ovych", "ovycha", "ovychu", "ivny", "ivni", "ivnu", "ivnoyu", "ivno",
)  # fmt: skip
# Endings of case forms in Latin transliteration, longest first is applied by the code.
STEM_ENDINGS: Final = (
    "iyevi", "yevi", "iyem", "yem", "iyu", "iya", "ogo", "omu", "ymi", "ami", "iam", "oyu",
    "eyu", "oyi", "yim", "ovi", "evi", "om", "em", "ym", "im", "oy", "ey", "iy", "yi", "yu",
    "ia", "iu", "ie", "ya", "a", "o", "u", "e", "i", "y",
)  # fmt: skip
# Cyrillic -> Latin transliteration used for the stem key (UK and RU).
TRANSLITERATION: Final[dict[str, str]] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "є": "ye",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "yi", "й": "y", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ь": "", "ъ": "",
    "ы": "y", "э": "e", "ю": "yu", "я": "ya", "ё": "e", "'": "", "’": "", "ʼ": "",
}  # fmt: skip

# --- top-level domains of bare domains -------------------------------------------------------
TLDS: Final = (
    "com", "net", "org", "edu", "gov", "info", "biz", "io", "co", "ua", "ru", "by", "kz",
    "pl", "de", "uk", "eu", "us", "me", "tv", "pro", "online", "site", "shop", "store",
    "tech", "app", "dev", "xyz", "top", "club", "cc", "fr", "it", "es", "nl", "cz", "ch",
    "at", "ro", "md", "lt", "lv", "ee", "ge", "am", "az", "kg", "uz", "tr", "cn", "jp",
    "in", "ca", "au", "ai", "su", "mobi", "name", "link", "live", "cloud", "agency",
)  # fmt: skip

# Countries of IBAN with the total length.
IBAN_LENGTHS: Final[dict[str, int]] = {
    "UA": 29, "GB": 22, "DE": 22, "PL": 28, "FR": 27, "IT": 27, "ES": 24, "NL": 18, "CH": 21,
    "AT": 20, "BE": 16, "CZ": 24, "SK": 24, "HU": 28, "RO": 24, "BG": 22, "LT": 20, "LV": 21,
    "EE": 20, "MD": 24, "GE": 22, "TR": 26, "KZ": 20, "AZ": 28, "BY": 28, "RU": 33, "CY": 28,
    "IE": 22, "PT": 25, "SE": 24, "NO": 15, "DK": 18, "FI": 18, "GR": 27, "LU": 20, "MT": 31,
    "HR": 21, "SI": 19, "RS": 22, "LI": 21, "IS": 26, "AE": 23, "SA": 24, "IL": 23,
}  # fmt: skip
