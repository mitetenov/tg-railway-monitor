"""Tests for the i18n module — Translation loading, lookup, interpolation, and pluralisation."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from i18n import (
    Translation,
    _interpolate,
    _select_plural_form,
    clear_cache,
    get_translation,
    load_translations,
    translate_station_name,
)


# ═══════════════════════ Helpers ═══════════════════════════════════════


def _tmp_locale(lang: str, data: dict) -> str:
    """Write *data* as messages.json under a temp dir and return the dir."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, lang, "messages.json")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return d


# ═══════════════════════ _select_plural_form ══════════════════════════


class TestSelectPluralForm:
    def test_en_singular(self):
        assert _select_plural_form(1, "en") == "one"

    def test_en_plural(self):
        assert _select_plural_form(0, "en") == "other"
        assert _select_plural_form(2, "en") == "other"
        assert _select_plural_form(100, "en") == "other"

    def test_ru_one(self):
        assert _select_plural_form(1, "ru") == "one"
        assert _select_plural_form(21, "ru") == "one"
        assert _select_plural_form(101, "ru") == "one"

    def test_ru_few(self):
        assert _select_plural_form(2, "ru") == "few"
        assert _select_plural_form(3, "ru") == "few"
        assert _select_plural_form(22, "ru") == "few"

    def test_ru_many(self):
        assert _select_plural_form(0, "ru") == "many"
        assert _select_plural_form(5, "ru") == "many"
        assert _select_plural_form(11, "ru") == "many"
        assert _select_plural_form(20, "ru") == "many"


# ═══════════════════════ _interpolate ═════════════════════════════════


class TestInterpolate:
    def test_no_op(self):
        assert _interpolate("Hello", {}) == "Hello"

    def test_basic(self):
        assert _interpolate("Hello {name}", {"name": "World"}) == "Hello World"

    def test_multiple(self):
        result = _interpolate("{a} + {b} = {c}", {"a": "1", "b": "2", "c": "3"})
        assert result == "1 + 2 = 3"

    def test_missing_key_left_as_is(self):
        """Missing interpolation keys remain as-is in output."""
        assert _interpolate("Hello {name}", {}) == "Hello {name}"

    def test_non_string_coerced(self):
        assert _interpolate("{count}", {"count": 42}) == "42"


# ═══════════════════════ Translation class ════════════════════════════


class TestTranslationLookup:
    def test_basic_lookup(self):
        t = Translation("en", {"greeting": "Hello"})
        assert t("greeting") == "Hello"

    def test_dotted_key(self):
        data = {"start": {"welcome": "👋 Hello!"}}
        t = Translation("en", data)
        assert t("start.welcome") == "👋 Hello!"

    def test_deeply_nested(self):
        data = {"a": {"b": {"c": "deep"}}}
        t = Translation("en", data)
        assert t("a.b.c") == "deep"

    def test_missing_key_returns_question_mark(self):
        """Missing key returns ?key? so developers notice."""
        t = Translation("en", {})
        assert t("missing") == "?missing?"

    def test_interpolation(self):
        t = Translation("en", {"greeting": "Hello {name}"})
        assert t("greeting", name="Alice") == "Hello Alice"

    def test_interpolation_multiple(self):
        t = Translation("en", {"route": "{origin} → {dest}"})
        assert t("route", origin="Tbilisi", dest="Batumi") == "Tbilisi → Batumi"

    def test_empty_data(self):
        t = Translation("en", {})
        assert t("anything") == "?anything?"

    def test_key_count(self):
        t = Translation("en", {"a": "1", "b": "2", "c": {"d": "3"}})
        # Top-level keys only
        assert t.key_count == 3

    def test_repr(self):
        t = Translation("en", {"a": "1"})
        assert "Translation(lang='en'" in repr(t)
        assert "keys=1" in repr(t)


# ═══════════════════════ Pluralisation ════════════════════════════════


class TestPluralisation:
    def test_en_singular(self):
        t = Translation("en", {"n_seats": {"one": "{count} seat", "other": "{count} seats"}})
        assert t.ngettext("n_seats", count=1) == "1 seat"

    def test_en_plural(self):
        t = Translation("en", {"n_seats": {"one": "{count} seat", "other": "{count} seats"}})
        assert t.ngettext("n_seats", count=5) == "5 seats"
        assert t.ngettext("n_seats", count=0) == "0 seats"
        assert t.ngettext("n_seats", count=100) == "100 seats"

    def test_ru_plural(self):
        data = {
            "n_seats": {
                "one": "{count} место",
                "few": "{count} места",
                "many": "{count} мест",
                "other": "{count} мест",
            }
        }
        t = Translation("ru", data)
        assert t.ngettext("n_seats", count=1) == "1 место"
        assert t.ngettext("n_seats", count=2) == "2 места"
        assert t.ngettext("n_seats", count=5) == "5 мест"
        assert t.ngettext("n_seats", count=11) == "11 мест"
        assert t.ngettext("n_seats", count=22) == "22 места"

    def test_plural_missing_key_returns_question(self):
        t = Translation("en", {})
        assert t.ngettext("missing", count=5) == "?missing?"

    def test_plural_flat_string_fallback(self):
        """When the translation is a flat string (not a dict), use it as-is."""
        t = Translation("en", {"n_seats": "{count} seats"})
        assert t.ngettext("n_seats", count=1) == "1 seats"
        assert t.ngettext("n_seats", count=5) == "5 seats"

    def test_plural_extra_kwargs(self):
        t = Translation("en", {"ticket": {"one": "{count} ticket for {route}", "other": "{count} tickets for {route}"}})
        assert t.ngettext("ticket", count=1, route="Tbilisi→Batumi") == "1 ticket for Tbilisi→Batumi"
        assert t.ngettext("ticket", count=3, route="Tbilisi→Batumi") == "3 tickets for Tbilisi→Batumi"


# ═══════════════════════ load_translations ════════════════════════════


class TestLoadTranslations:
    def test_load_valid(self):
        d = _tmp_locale("en", {"greeting": "Hello"})
        data = load_translations("en", locale_dir=d)
        assert data == {"greeting": "Hello"}

    def test_load_missing_file(self):
        data = load_translations("xx", locale_dir="/tmp/nonexistent")
        assert data == {}

    def test_load_invalid_json(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "en", "messages.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write("not json")
        data = load_translations("en", locale_dir=d)
        assert data == {}


# ═══════════════════════ get_translation / cache ══════════════════════


class TestGetTranslation:
    def test_returns_cached_instance(self):
        clear_cache()
        t1 = get_translation("en")
        t2 = get_translation("en")
        assert t1 is t2

    def test_different_langs(self):
        clear_cache()
        t_en = get_translation("en")
        t_ru = get_translation("ru")
        assert t_en is not t_ru
        assert t_en.lang == "en"
        assert t_ru.lang == "ru"

    def test_clear_cache(self):
        clear_cache()
        t1 = get_translation("en")
        clear_cache()
        t2 = get_translation("en")
        assert t1 is not t2

    def test_unknown_lang_fallback_empty(self):
        """Unknown language returns an empty Translation (no crash)."""
        clear_cache()
        t = get_translation("fr")
        assert t("anything") == "?anything?"


# ═══════════════════════ Real locale files (integration) ═════════════


class TestRealLocaleFiles:
    """Tests that actually load the project's en.json and ru.json."""

    def test_en_loads(self):
        clear_cache()
        t = get_translation("en")
        assert t.key_count > 0
        assert t("start.welcome") != "?start.welcome?"
        assert t("start.description") != "?start.description?"

    def test_ru_loads(self):
        clear_cache()
        t = get_translation("ru")
        assert t.key_count > 0
        assert t("start.welcome") != "?start.welcome?"

    def test_en_has_all_expected_sections(self):
        clear_cache()
        t = get_translation("en")
        expected_sections = [
            "start", "wizard", "stop",
            "fallback", "poller", "button", "n_seats",
        ]
        for section in expected_sections:
            # Each section must have at least one non-empty top-level key
            entry = t._data.get(section, {})
            assert entry, f"Section '{section}' is missing from en.json"
            assert isinstance(entry, dict), f"Section '{section}' is not a dict"
            assert len(entry) > 0, f"Section '{section}' is empty"

    def test_ru_has_plural_forms(self):
        clear_cache()
        t = get_translation("ru")
        assert t.ngettext("n_seats", count=1) != "?n_seats?"
        assert t.ngettext("n_seats", count=2) != "?n_seats?"
        assert t.ngettext("n_seats", count=5) != "?n_seats?"

    def test_en_plural_singular(self):
        clear_cache()
        t = get_translation("en")
        result = t.ngettext("n_seats", count=1)
        assert "1" in result
        assert "seat" in result
        # singular form does not have trailing 's'
        assert not result.endswith("seats")

    def test_en_plural_multiple(self):
        clear_cache()
        t = get_translation("en")
        result = t.ngettext("n_seats", count=5)
        assert "5" in result
        assert "seats" in result

    def test_en_interpolation_route_line(self):
        clear_cache()
        t = get_translation("en")
        result = t("start.route_line", from_name="Tbilisi", to_name="Batumi")
        assert "🚉" in result
        assert "Tbilisi" in result
        assert "Batumi" in result

# ═══════════════════════ translate_station_name ═══════════════════


class TestTranslateStationName:
    """Tests for translate_station_name(code, lang) — int-code-based."""

    # ── English ────────────────────────────────────────────────────

    def test_en_known_station(self):
        """English should return the canonical name for a known code."""
        result = translate_station_name(56014, "en")
        assert result == "Tbilisi"

    def test_en_batumi(self):
        result = translate_station_name(57151, "en")
        assert result == "Batumi"

    def test_en_airport(self):
        result = translate_station_name(57450, "en")
        assert result == "Kutaisi Airport"

    def test_en_kutaisi_city(self):
        """Kutaisi city center (57530) should be in English."""
        result = translate_station_name(57530, "en")
        assert result == "Kutaisi"

    def test_en_zugdidi(self):
        result = translate_station_name(57290, "en")
        assert result == "Zugdidi"

    def test_en_kobuleti(self):
        result = translate_station_name(57120, "en")
        assert result == "Kobuleti"

    def test_en_unknown_code_fallback(self):
        """Unknown code falls back to string representation."""
        result = translate_station_name(99999, "en")
        assert result == "99999"

    def test_en_negative_code_fallback(self):
        """Negative codes fall back gracefully."""
        result = translate_station_name(-1, "en")
        assert result == "-1"

    # ── Russian ────────────────────────────────────────────────────

    def test_ru_known_station(self):
        """Known station should return the Russian name."""
        result = translate_station_name(56014, "ru")
        assert result == "Тбилиси"

    def test_ru_batumi(self):
        result = translate_station_name(57151, "ru")
        assert result == "Батуми"

    def test_ru_airport(self):
        result = translate_station_name(57450, "ru")
        assert result == "Аэропорт Кутаиси"

    def test_ru_kutaisi_city(self):
        """Kutaisi city center has a Russian translation."""
        result = translate_station_name(57530, "ru")
        assert result == "Кутаиси"

    def test_ru_zugdidi(self):
        result = translate_station_name(57290, "ru")
        assert result == "Зугдиди"

    def test_ru_kobuleti(self):
        result = translate_station_name(57120, "ru")
        assert result == "Кобулети"

    def test_ru_ozurgeti(self):
        result = translate_station_name(57100, "ru")
        assert result == "Озургети"

    def test_ru_unknown_code_fallback(self):
        """Unknown code falls back to English name (stringified code)."""
        result = translate_station_name(99999, "ru")
        assert result == "99999"

    # ── Georgian ──────────────────────────────────────────────────

    def test_ka_known_station(self):
        """Known station should return the Georgian name."""
        result = translate_station_name(56014, "ka")
        assert result == "თბილისი"

    def test_ka_batumi(self):
        result = translate_station_name(57151, "ka")
        assert result == "ბათუმი"

    def test_ka_airport(self):
        result = translate_station_name(57450, "ka")
        assert result == "ქუთაისის საერთაშორისო აეროპორტი"

    def test_ka_kutaisi_city(self):
        """Kutaisi city center has a Georgian translation."""
        result = translate_station_name(57530, "ka")
        assert result == "ქუთაისი"

    def test_ka_poti(self):
        result = translate_station_name(57210, "ka")
        assert result == "ფოთი"

    def test_ka_unknown_code_fallback(self):
        """Unknown code falls back to string representation."""
        result = translate_station_name(99999, "ka")
        assert result == "99999"

    # ── Fallback for unsupported languages ─────────────────────────

    def test_unsupported_lang_falls_back_to_en(self):
        """Unsupported language code returns the English name."""
        result = translate_station_name(56014, "fr")
        assert result == "Tbilisi"

    # ── Fallback parameter ──────────────────────────────────────────

    def test_fallback_used_when_code_unknown(self):
        """Unknown code returns fallback when provided."""
        result = translate_station_name(99999, "en", fallback="Unknown Station")
        assert result == "Unknown Station"

    def test_fallback_ru_unknown(self):
        """Unknown code in Russian returns fallback when provided."""
        result = translate_station_name(99999, "ru", fallback="Неизвестно")
        assert result == "Неизвестно"

    def test_fallback_ka_unknown(self):
        """Unknown code in Georgian returns fallback when provided."""
        result = translate_station_name(99999, "ka", fallback="უცნობი")
        assert result == "უცნობი"

    def test_fallback_not_used_when_translation_known(self):
        """Fallback is ignored when a translation exists."""
        result = translate_station_name(56014, "en", fallback="N/A")
        assert result == "Tbilisi"
        result_ru = translate_station_name(56014, "ru", fallback="N/A")
        assert result_ru == "Тбилиси"
        result_ka = translate_station_name(56014, "ka", fallback="N/A")
        assert result_ka == "თბილისი"

    def test_fallback_none_default(self):
        """fallback=None (default) returns stringified code like before."""
        result_en = translate_station_name(99999, "en")
        result_ru = translate_station_name(99999, "ru")
        result_ka = translate_station_name(99999, "ka")
        assert result_en == "99999"
        assert result_ru == "99999"
        assert result_ka == "99999"

    def test_fallback_empty_string(self):
        """Empty string fallback is returned as-is when code unknown."""
        result = translate_station_name(99999, "en", fallback="")
        assert result == ""

    # ── All known codes in RU ─────────────────────────────────────

    def test_ru_all_codes_have_translation(self):
        """Every code in _STATION_DATA with a code has a Russian translation."""
        from stations import STATION_NAMES_RU, _STATION_DATA  # noqa: PLC0415

        for code_str, _, _, _, _ in _STATION_DATA:
            if not code_str:
                continue
            code = int(code_str)
            translated = translate_station_name(code, "ru")
            expected = STATION_NAMES_RU[code]
            assert translated == expected, (
                f"Code {code} expected '{expected}', got '{translated}'"
            )

    # ── All known codes in KA ─────────────────────────────────────

    def test_ka_all_codes_have_translation(self):
        """Every code in _STATION_DATA with a code has a Georgian translation."""
        from stations import STATION_NAMES_KA, _STATION_DATA  # noqa: PLC0415

        for code_str, _, _, _, _ in _STATION_DATA:
            if not code_str:
                continue
            code = int(code_str)
            translated = translate_station_name(code, "ka")
            expected = STATION_NAMES_KA[code]
            assert translated == expected, (
                f"Code {code} expected '{expected}', got '{translated}'"
            )

    # ── Consistency checks ────────────────────────────────────────

    def test_ru_all_codes_distinct(self):
        """Russian translations should all be distinct."""
        from stations import STATION_NAMES_RU
        assert len(set(STATION_NAMES_RU.values())) == len(STATION_NAMES_RU), (
            "Duplicate Russian translation detected"
        )

    def test_ka_all_codes_distinct(self):
        """Georgian translations should all be distinct."""
        from stations import STATION_NAMES_KA
        assert len(set(STATION_NAMES_KA.values())) == len(STATION_NAMES_KA), (
            "Duplicate Georgian translation detected"
        )

    def test_idempotent_en(self):
        """Calling twice with same args returns same result."""
        assert translate_station_name(56014, "en") == translate_station_name(56014, "en")

    def test_idempotent_ru(self):
        assert translate_station_name(57151, "ru") == translate_station_name(57151, "ru")

    def test_idempotent_ka(self):
        assert translate_station_name(57450, "ka") == translate_station_name(57450, "ka")

    # ── Parametrized codes ────────────────────────────────────────

    def test_parametrized_codes(self):
        """A handful of diverse codes in all languages."""
        codes = [56014, 57151, 57450, 57530, 57290, 57120]
        for code in codes:
            en = translate_station_name(code, "en")
            ru = translate_station_name(code, "ru")
            ka = translate_station_name(code, "ka")
            assert en, f"Empty English for code {code}"
            assert ru, f"Empty Russian for code {code}"
            assert ka, f"Empty Georgian for code {code}"
            # Each language should be different (not fallback)
            assert ru != en or ru == str(code), f"Russian fell back to English for code {code}"
            assert ka != en or ka == str(code), f"Georgian fell back to English for code {code}"

    # ═══════════════════════ Wizard keys ════════════════════════════════

    def test_en_wizard_date_select(self):
        clear_cache()
        t = get_translation("en")
        assert t("wizard.date_select") != "?wizard.date_select?"

    def test_en_wizard_date_buttons(self):
        clear_cache()
        t = get_translation("en")
        assert t("wizard.date_today_btn") != "?wizard.date_today_btn?"
        assert t("wizard.date_tomorrow_btn") != "?wizard.date_tomorrow_btn?"
        assert t("wizard.date_custom_btn") != "?wizard.date_custom_btn?"

    def test_en_wizard_station_buttons(self):
        clear_cache()
        t = get_translation("en")
        assert "Tbilisi" in t("wizard.station_tbilisi_btn")
        assert "Batumi" in t("wizard.station_batumi_btn")
        assert t("wizard.station_all_btn") != "?wizard.station_all_btn?"

    def test_en_wizard_class_buttons(self):
        clear_cache()
        t = get_translation("en")
        assert t("wizard.class_any_btn") != "?wizard.class_any_btn?"
        assert t("wizard.class_business_btn") != "?wizard.class_business_btn?"
        assert t("wizard.class_i_btn") != "?wizard.class_i_btn?"
        assert t("wizard.class_ii_btn") != "?wizard.class_ii_btn?"

    def test_en_wizard_monitoring_started(self):
        clear_cache()
        t = get_translation("en")
        msg = t("wizard.monitoring_started")
        assert "Monitoring started" in msg or "All set" in msg
        assert "/stop" in msg

    def test_en_wizard_stop_confirm(self):
        clear_cache()
        t = get_translation("en")
        assert t("wizard.stop_confirm") != "?wizard.stop_confirm?"
        assert t("wizard.stop_confirm_btn") != "?wizard.stop_confirm_btn?"
        assert t("wizard.stop_cancel_btn") != "?wizard.stop_cancel_btn?"

    def test_en_wizard_interpolation(self):
        clear_cache()
        t = get_translation("en")
        result = t("wizard.route_saved", from_name="Tbilisi", to_name="Batumi")
        assert "Tbilisi" in result
        assert "Batumi" in result
        result2 = t("wizard.class_set", class_name="Business")
        assert "Business" in result2
        result3 = t("wizard.date_set", date="2026-07-15")
        assert "2026-07-15" in result3

    def test_ru_wizard_sections(self):
        clear_cache()
        t = get_translation("ru")
        assert t("wizard.date_select") != "?wizard.date_select?"
        assert t("wizard.select_departure") != "?wizard.select_departure?"
        assert t("wizard.select_class") != "?wizard.select_class?"
        assert t("wizard.monitoring_started") != "?wizard.monitoring_started?"
