"""Single source of truth for Georgian Railway station data.

Every station is defined once in ``_STATION_DATA`` and all public
mappings (code→name, name→slug, etc.) are derived from it.

Import this module anywhere you need station info — no more scattered
FALLBACK_STATIONS / STATION_NAMES / STATION_SLUGS duplicates.
"""

# ── Master list ──────────────────────────────────────────────────────
# (code, english_name, slug, is_popular, georgian_name)
_STATION_DATA: list[tuple[str, str, str, bool, str]] = [
    ("56014", "Tbilisi",              "Tbilisi",           True,  "თბილისი"),
    ("56040", "Mtskheta",             "Mtskheta",          False, "მცხეთა"),
    ("56080", "Kaspi",                "Kaspi",             False, "კასპი"),
    ("57000", "Samtredia",            "Samtredia",         True,  "სამტრედია"),
    ("57030", "Nigoiti",              "Nigoiti",           False, "ნიგოითი"),
    ("57031", "Shukhuti",             "Shukhuti",          False, "შუხუთი"),
    ("57040", "Lanchkhuti",           "Lanchkhuti",        False, "ლანჩხუთი"),
    ("57050", "Jumati",               "Jumati",            False, "ჯუმათი"),
    ("57060", "Supsa",                "Supsa",             False, "სუფსა"),
    ("57070", "Ureki",                "Ureki",             False, "ურეკი"),
    ("57080", "Natanebi",             "Natanebi",          False, "ნატანები"),
    ("57090", "Meria",                "Meria",             False, "მერია"),
    ("57100", "Ozurgeti",             "Ozurgeti",          True,  "ოზურგეთი"),
    ("57120", "Kobuleti",             "Kobuleti",          True,  "ქობულეთი"),
    ("57151", "Batumi",               "Batumi",            True,  "ბათუმი"),
    ("57170", "Abasha",               "Abasha",            False, "აბაშა"),
    ("57190", "Senaki",               "Senaki",            True,  "სენაკი"),
    ("57194", "Kvaloni",              "Kvaloni",           False, "ქვალონი"),
    ("57202", "Chaladidi",            "Chaladidi",         False, "ჭალადიდი"),
    ("57210", "Poti",                 "Poti",              True,  "ფოთი"),
    ("57250", "Khobi",                "Khobi",             False, "ხობი"),
    ("57252", "Kheta",                "Kheta",             False, "ხეთა"),
    ("57280", "Ingiri",               "Ingiri",            False, "ინგირი"),
    ("57290", "Zugdidi",              "Zugdidi",           True,  "ზუგდიდი"),
    ("57450", "Kutaisi Airport",      "Kutaisi%20Airport", True,  "ქუთაისის საერთაშორისო აეროპორტი"),
    ("57510", "Rioni",                "Rioni",             False, "რიონი"),
    ("57530", "Kutaisi",              "Kutaisi",           True,  "ქუთაისი"),
    ("57580", "Sviri",                "Sviri",             False, "სვირი"),
    ("57600", "Zestafoni",            "Zestafoni",         False, "ზესტაფონი"),
    ("57670", "Dzirula",              "Dzirula",           False, "ძირულა"),
    ("57680", "Kharagauli",           "Kharagauli",        False, "ხარაგაული"),
    ("57690", "Marelisi",             "Marelisi",          False, "მარელისი"),
    ("57700", "Moliti",               "Moliti",            False, "მოლითი"),
    ("57702", "Tsifa",                "Tsifa",             False, "წიფა"),
    ("57720", "Khashuri",             "Khashuri",          False, "ხაშური"),
    ("57880", "Kareli",               "Kareli",            False, "ყარელი"),
    ("57900", "Gori",                 "Gori",              False, "გორი"),
    ("",      "Borjomi",              "Borjomi",           False, "ბორჯომი"),
    ("",      "Akhaltsikhe",          "Akhaltsikhe",       False, "ახალციხე"),
]

# ── Derived mappings ─────────────────────────────────────────────────

STATION_NAMES: dict[int, str] = {
    int(code): name for code, name, *_ in _STATION_DATA if code
}
"""Code → English name, e.g. ``56014 → "Tbilisi"``."""

STATION_SLUGS: dict[str, str] = {
    name: slug for _, name, slug, *_ in _STATION_DATA
}
"""English name → tre.ge URL slug, e.g. ``"Kutaisi Airport" → "Kutaisi%20Airport"``."""

SLUG_TO_STATION: dict[str, str] = {v: k for k, v in STATION_SLUGS.items()}
"""Reverse of STATION_SLUGS: slug → English name."""

FALLBACK_STATIONS: list[dict] = [
    {"code": code, "stationName": name, "isPopular": popular}
    for code, name, _, popular, _ in _STATION_DATA
]
"""Backward-compatible fallback list used by bot.py when the API is down."""

# ── Localised names (code-keyed) ─────────────────────────────────────────

STATION_NAMES_RU: dict[int, str] = {
    56014: "Тбилиси",
    56040: "Мцхета",
    56080: "Каспи",
    57000: "Самтредиа",
    57030: "Нигоити",
    57031: "Шухути",
    57040: "Ланчхути",
    57050: "Джумати",
    57060: "Супса",
    57070: "Уреки",
    57080: "Натанеби",
    57090: "Мерия",
    57100: "Озургети",
    57120: "Кобулети",
    57151: "Батуми",
    57170: "Абаша",
    57190: "Сенаки",
    57194: "Квалони",
    57202: "Чаладиди",
    57210: "Поти",
    57250: "Хоби",
    57252: "Хета",
    57280: "Ингири",
    57290: "Зугдиди",
    57450: "Аэропорт Кутаиси",
    57510: "Риони",
    57530: "Кутаиси",
    57580: "Свири",
    57600: "Зестафони",
    57670: "Дзирула",
    57680: "Харагаули",
    57690: "Марелиси",
    57700: "Молити",
    57702: "Цифа",
    57720: "Хашури",
    57880: "Карели",
    57900: "Гори",
}
"""Code → Russian name, e.g. ``56014 → "Тбилиси"``.

Only stations with a known station code are included.
Stations without a code (Borjomi, Akhaltsikhe) are excluded.
"""

STATION_NAMES_KA: dict[int, str] = {
    int(code): geo for code, _, _, _, geo in _STATION_DATA if code
}
"""Code → Georgian (ქართული) name, e.g. ``56014 → "თბილისი"``.
Derived from ``_STATION_DATA``.
"""

# ── Helpers ──────────────────────────────────────────────────────────

def station_to_slug(name: str) -> str:
    """Convert a station name to a tre.ge URL slug.

    Accepts case-insensitive input and falls back to URL-encoding
    unknown names.
    """
    if name in STATION_SLUGS:
        return STATION_SLUGS[name]
    lower = name.lower().strip()
    for station_name, station_slug in STATION_SLUGS.items():
        if station_name.lower() == lower:
            return station_slug
    import urllib.parse
    return urllib.parse.quote(name, safe="")


def slug_to_station(slug: str) -> str | None:
    """Convert a tre.ge URL slug back to a station name."""
    return SLUG_TO_STATION.get(slug)
