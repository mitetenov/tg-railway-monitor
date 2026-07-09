"""
Internationalisation (i18n) support for tg-ticket-monitor.

Loads JSON locale files from ``locales/{lang}/messages.json`` and provides
a ``Translation`` class with interpolation and simple pluralisation.

Usage::

    from i18n import get_translation

    t = get_translation("en")
    msg = t("start_welcome")
    msg = t("route_saved", from_name="Tbilisi", to_name="Batumi")
    msg = t.ngettext("n_seats", seats, count=seats)
"""

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")

# ── Simple pluralisation rule helpers ────────────────────────────────────────

# Keyed by language code; each entry is a list of (condition_fn, plural_key).
# condition_fn receives the integer count and returns True when that form matches.
_PLURAL_RULES: dict[str, list[tuple]] = {
    # English: 1 → singular, everything else → plural
    "en": [
        (lambda n: n == 1, "one"),
        (lambda n: n != 1, "other"),
    ],
    # Russian: 1 → singular, 2-4 → few, 0/5+ → many
    "ru": [
        (lambda n: n % 10 == 1 and n % 100 != 11, "one"),
        (lambda n: 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20), "few"),
        (lambda n: n % 10 == 0 or 5 <= n % 10 <= 9 or 11 <= n % 100 <= 20, "many"),
        (lambda n: True, "other"),  # fallback
    ],
}


def _select_plural_form(count: int, lang: str) -> str:
    """Return the plural-form key (``one``/``few``/``many``/``other``) for *count*."""
    rules = _PLURAL_RULES.get(lang, _PLURAL_RULES.get("en", []))
    for cond, form in rules:
        if cond(count):
            return form
    return "other"


# ── Translation class ────────────────────────────────────────────────────────


class Translation:
    """Thin wrapper around a JSON translation dict.

    Parameters
    ----------
    lang : str
        Language code (e.g. ``"en"``, ``"ru"``).
    data : dict
        Flat or nested dict of key → translated string.
        Pluralisable entries should be a dict ``{"one": "...", "other": "..."}``.
    """

    def __init__(self, lang: str, data: dict) -> None:
        self._lang = lang
        self._data = data

    @property
    def lang(self) -> str:
        return self._lang

    @property
    def key_count(self) -> int:
        """Number of top-level translation keys loaded."""
        return len(self._data)

    # ── Public API ───────────────────────────────────────────────────────────

    def __call__(self, key: str, /, **kwargs) -> str:
        """Look up *key* and interpolate ``{name}`` placeholders with **kwargs.

        Returns the raw *key* (with ``?`` prefix) when no translation is found,
        making missing keys visible during development.
        """
        raw = self._resolve(key)
        if raw is None:
            logger.debug("Missing translation key '%s' for lang '%s'", key, self._lang)
            return f"?{key}?"
        if kwargs:
            return _interpolate(raw, kwargs)
        return raw

    def ngettext(self, key: str, *, count: int, **kwargs) -> str:
        """Pluralisation-aware lookup.

        The translation entry for *key* should be a dict with plural forms::

            {"one": "{count} seat", "other": "{count} seats"}

        ``count`` is automatically injected into interpolation kwargs and
        the correct plural form is selected based on the language rules.
        """
        raw = self._resolve(key)
        if raw is None:
            logger.debug("Missing plural key '%s' for lang '%s'", key, self._lang)
            return f"?{key}?"

        if isinstance(raw, dict):
            form = _select_plural_form(count, self._lang)
            template = str(raw.get(form) or raw.get("other", ""))
            if not template:
                return f"?{key}.{form}?"
        else:
            # Fallback: single string used as-is (no plural form selection)
            template = str(raw) if raw is not None else ""

        all_kwargs = dict(kwargs, count=count)
        return _interpolate(template, all_kwargs)

    def __repr__(self) -> str:
        return f"Translation(lang='{self._lang}', keys={len(self._data)})"

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _resolve(self, key: str):
        """Walk dotted keys through nested dicts."""
        parts = key.split(".")
        node = self._data
        for part in parts:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return None
        return node


# ── Interpolation ────────────────────────────────────────────────────────────

_INTERP_RE = re.compile(r"\{(\w+)\}")


def _interpolate(template: str, kwargs: dict) -> str:
    """Replace ``{name}`` placeholders with values from *kwargs*.

    Missing keys are left as-is in the output rather than raising.
    """
    def _replacer(m: re.Match) -> str:
        name = m.group(1)
        return str(kwargs.get(name, m.group(0)))
    return _INTERP_RE.sub(_replacer, template)


# ── Module-level helpers ─────────────────────────────────────────────────────


def load_translations(lang: str, locale_dir: Optional[str] = None) -> dict:
    """Load JSON translation data for *lang*.

    Returns an empty dict when the file is missing or unreadable.
    """
    dir_path = locale_dir or LOCALE_DIR
    path = os.path.join(dir_path, lang, "messages.json")
    if not os.path.isfile(path):
        logger.warning("Locale file not found: %s", path)
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load locale %s: %s", path, e)
        return {}


# Simple in-memory cache so we don't re-read JSON files on every lookup
_cache: dict[str, Translation] = {}


def get_translation(lang: str = "en") -> Translation:
    """Return a cached ``Translation`` for the given language code."""
    if lang not in _cache:
        data = load_translations(lang)
        _cache[lang] = Translation(lang, data)
    return _cache[lang]


def clear_cache() -> None:
    """Purge cached translations (useful in tests)."""
    _cache.clear()


# ═══════════════════ User language detection & storage ════════════════

SUPPORTED_LANGUAGES = frozenset({"en", "ru"})

# In-memory cache: chat_id -> language code (backed by persistent config)
_user_lang_cache: dict[int, str] = {}


def _normalize_lang(lang_code: Optional[str]) -> str:
    """Normalise an IETF language tag to a supported language code.

    Handles regional variants (``"en-US"`` → ``"en"``) and missing or
    ``None`` input (→ ``"en"``). Returns ``"en"`` for unsupported languages.
    """
    if not lang_code:
        return "en"
    lang = lang_code.split("-")[0].lower()
    return lang if lang in SUPPORTED_LANGUAGES else "en"


def detect_and_store_language(chat_id: int, user=None) -> str:
    """Detect a user's language, persist it, and cache it in memory.

    When a language is already stored in the chat's config file, it is
    returned immediately.  Otherwise the language is inferred from
    *user*.\ ``language_code`` (the Telegram User object), normalised,
    saved to the persistent config dict, and cached in-memory.

    Parameters
    ----------
    chat_id : int
        Telegram chat ID (used as the persistence key).
    user : object or None
        A Telegram ``User`` instance with a ``language_code`` attribute,
        or ``None`` to skip detection and default to ``"en"``.

    Returns
    -------
    str
        A supported language code (``"en"`` or ``"ru"``).
    """
    from config_manager import load_config, save_config  # noqa: PLC0415

    config = load_config(chat_id)
    stored = config.get("language")
    if stored and stored in SUPPORTED_LANGUAGES:
        _user_lang_cache[chat_id] = stored
        return stored

    lang = "en"
    if user is not None and hasattr(user, "language_code"):
        lang = _normalize_lang(user.language_code)

    config["language"] = lang
    save_config(chat_id, config)
    _user_lang_cache[chat_id] = lang
    return lang


def get_user_language(chat_id: int, user=None) -> str:
    """Return the stored or detected language for *chat_id*.

    The in-memory cache is checked first; on a cache miss the persistent
    config is consulted (and refreshed into the cache).  If no stored
    language exists, detection falls through to *user*.
    """
    cached = _user_lang_cache.get(chat_id)
    if cached is not None:
        return cached
    return detect_and_store_language(chat_id, user)


def get_user_translation(chat_id: int, user=None) -> Translation:
    """Return a ``Translation`` instance for the user's language."""
    lang = get_user_language(chat_id, user)
    return get_translation(lang)


def clear_user_lang_cache() -> None:
    """Purge the in-memory user-language cache (useful in tests)."""
    _user_lang_cache.clear()


# ═══════════════════ Station name translation ═════════════════════


def translate_station_name(code: int, lang: str = "en") -> str:
    """Return a station name localised to *lang*.

    Parameters
    ----------
    code : int
        Station code (e.g. ``56014`` for Tbilisi).
    lang : str
        Target language code (``"en"``, ``"ru"``, ``"ka"``).
        Falls back to English for unknown languages.

    Returns
    -------
    str
        The station name in the requested language, or the string
        representation of *code* when no translation is available.
    """
    from stations import STATION_NAMES, STATION_NAMES_RU, STATION_NAMES_KA  # noqa: PLC0415

    fallback = str(code)
    if lang == "ru":
        return STATION_NAMES_RU.get(code, STATION_NAMES.get(code, fallback))
    if lang == "ka":
        return STATION_NAMES_KA.get(code, STATION_NAMES.get(code, fallback))
    # Default: English
    return STATION_NAMES.get(code, fallback)
