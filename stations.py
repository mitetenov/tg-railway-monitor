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
    ("57151", "Batumi",               "Batumi",            True,  "ბათუმი"),
    ("57450", "Kutaisi Airport",      "Kutaisi%20Airport", True,  "ქუთაისის საერთაშორისო აეროპორტი"),
    ("57530", "Kutaisi",              "Kutaisi",           True,  "ქუთაისი"),
    ("57290", "Zugdidi",              "Zugdidi",           True,  "ზუგდიდი"),
    ("57120", "Kobuleti",             "Kobuleti",          True,  "ქობულეთი"),
    ("57100", "Ozurgeti",             "Ozurgeti",          True,  "ოზურგეთი"),
    ("57190", "Senaki",               "Senaki",            True,  "სენაკი"),
    ("57000", "Samtredia",            "Samtredia",         True,  "სამტრედია"),
    ("57070", "Ureki",                "Ureki",             False, "ურეკი"),
    ("57210", "Poti",                 "Poti",              True,  "ფოთი"),
    ("57900", "Gori",                 "Gori",              False, "გორი"),
    ("57720", "Khashuri",             "Khashuri",          False, "ხაშური"),
    ("57600", "Zestafoni",            "Zestafoni",         False, "ზესტაფონი"),
    ("57510", "Rioni",                "Rioni",             False, "რიონი"),
    ("57030", "Nigoiti",              "Nigoiti",           False, "ნიგოითი"),
    ("56040", "Mtskheta",             "Mtskheta",          False, "მცხეთა"),
    ("56080", "Kaspi",                "Kaspi",             False, "კასპი"),
    ("",      "Borjomi",              "Borjomi",           False, "ბორჯომი"),
    ("",      "Akhaltsikhe",          "Akhaltsikhe",       False, "ახალციხე"),
]

# ── Derived mappings ─────────────────────────────────────────────────

STATION_NAMES: dict[str, str] = {
    code: name for code, name, *_ in _STATION_DATA if code
}
"""Code → English name, e.g. ``"56014" → "Tbilisi"``."""

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
