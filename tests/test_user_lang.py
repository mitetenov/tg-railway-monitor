"""Tests for user language auto-detection and storage (i18n user-lang helpers)."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from i18n import (
    Translation,
    _normalize_lang,
    clear_cache,
    clear_user_lang_cache,
    detect_and_store_language,
    get_translation,
    get_user_language,
    get_user_translation,
)


# ═══════════════════════ Fake User object ═════════════════════════════


class FakeUser:
    """Minimal stand-in for a Telegram User with a language_code."""

    def __init__(self, language_code: str) -> None:
        self.language_code = language_code


# ═══════════════════════ _normalize_lang ══════════════════════════════


class TestNormalizeLang:
    def test_exact_supported(self):
        assert _normalize_lang("en") == "en"
        assert _normalize_lang("ru") == "ru"

    def test_regional_variant(self):
        assert _normalize_lang("en-US") == "en"
        assert _normalize_lang("en-GB") == "en"
        assert _normalize_lang("ru-RU") == "ru"

    def test_unsupported_falls_back_to_en(self):
        assert _normalize_lang("fr") == "en"
        assert _normalize_lang("de") == "en"
        assert _normalize_lang("es") == "en"

    def test_none_empty_returns_en(self):
        assert _normalize_lang(None) == "en"
        assert _normalize_lang("") == "en"

    def test_case_insensitive(self):
        assert _normalize_lang("EN") == "en"
        assert _normalize_lang("Ru") == "ru"
        assert _normalize_lang("EN-US") == "en"


# ═══════════════════════ detect_and_store_language ════════════════════


class TestDetectAndStoreLanguage:
    def _mock_config_dir(self) -> str:
        """Create a temp dir to serve as a per-test data directory.

        We monkey-patch config_manager.DATA_DIR by writing into a temp
        location.  The import is deferred so each test gets a clean dir.
        """
        import config_manager  # noqa: PLC0415

        d = tempfile.mkdtemp()
        config_manager.DATA_DIR = d
        return d

    def setup_method(self):
        clear_user_lang_cache()

    def test_detects_from_user_object(self):
        """First call with a RU user stores 'ru'."""
        self._mock_config_dir()
        lang = detect_and_store_language(12345, FakeUser("ru"))
        assert lang == "ru"

    def test_detects_from_regional_code(self):
        """Regional variant 'en-US' normalises to 'en'."""
        self._mock_config_dir()
        lang = detect_and_store_language(12346, FakeUser("en-US"))
        assert lang == "en"

    def test_unsupported_falls_back_to_en(self):
        """Unsupported language falls back to 'en'."""
        self._mock_config_dir()
        lang = detect_and_store_language(12347, FakeUser("fr"))
        assert lang == "en"

    def test_no_user_defaults_to_en(self):
        """When user is None, default to 'en'."""
        self._mock_config_dir()
        lang = detect_and_store_language(12348, None)
        assert lang == "en"

    def test_no_user_object_without_language_code(self):
        """User object without language_code attr defaults to 'en'."""

        class BareUser:
            pass

        self._mock_config_dir()
        lang = detect_and_store_language(12349, BareUser())
        assert lang == "en"

    def test_persists_to_config(self):
        """Language is written to the persistent config file."""
        data_dir = self._mock_config_dir()
        detect_and_store_language(12350, FakeUser("ru"))

        path = os.path.join(data_dir, "12350.json")
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        assert config.get("language") == "ru"

    def test_uses_stored_value_on_subsequent_call(self):
        """If config already has 'language', use it instead of re-detecting."""

        class DetectableUser:
            language_code = "ru"

        data_dir = self._mock_config_dir()

        # First call: detect from user -> ru
        detect_and_store_language(12351, DetectableUser())

        # Manually change config to 'en' (simulates admin override)
        path = os.path.join(data_dir, "12351.json")
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        config["language"] = "en"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f)

        # Second call should return 'en' from config, not re-detect from user
        clear_user_lang_cache()  # clear in-memory cache to force re-read
        lang = detect_and_store_language(12351, DetectableUser())
        assert lang == "en"

    def test_invalid_stored_language_is_overwritten(self):
        """If stored language is not supported, re-detect."""
        data_dir = self._mock_config_dir()

        # Write config with unsupported language
        path = os.path.join(data_dir, "12352.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"language": "fr"}, f)

        clear_user_lang_cache()
        lang = detect_and_store_language(12352, FakeUser("ru"))
        assert lang == "ru"  # re-detected


# ═══════════════════════ get_user_language ════════════════════════════


class TestGetUserLanguage:
    def _mock_config_dir(self) -> str:
        import config_manager  # noqa: PLC0415

        d = tempfile.mkdtemp()
        config_manager.DATA_DIR = d
        return d

    def setup_method(self):
        clear_user_lang_cache()

    def test_returns_from_cache(self):
        """Returns cached value without touching config."""
        import config_manager  # noqa: PLC0415

        data_dir = self._mock_config_dir()

        # First call detects and caches
        detect_and_store_language(12360, FakeUser("ru"))

        # Delete the config file to prove cache is used
        os.remove(os.path.join(data_dir, "12360.json"))

        lang = get_user_language(12360)
        assert lang == "ru"

    def test_detects_on_cache_miss(self):
        """Cache miss triggers detection from config or user."""
        self._mock_config_dir()
        lang = get_user_language(12361, FakeUser("en-GB"))
        assert lang == "en"

    def test_returns_existing_config_on_cache_miss(self):
        """If config exists but cache is cold, read from config."""
        data_dir = self._mock_config_dir()

        detect_and_store_language(12362, FakeUser("ru"))
        clear_user_lang_cache()

        lang = get_user_language(12362)  # no user passed — should read from config
        assert lang == "ru"


# ═══════════════════════ get_user_translation ═════════════════════════


class TestGetUserTranslation:
    def _mock_config_dir(self) -> str:
        import config_manager  # noqa: PLC0415

        d = tempfile.mkdtemp()
        config_manager.DATA_DIR = d
        return d

    def setup_method(self):
        clear_cache()
        clear_user_lang_cache()

    def test_returns_translation_for_user_lang(self):
        self._mock_config_dir()
        t = get_user_translation(12370, FakeUser("ru"))
        assert isinstance(t, Translation)
        assert t.lang == "ru"

    def test_en_user_gets_en_translation(self):
        self._mock_config_dir()
        t = get_user_translation(12371, FakeUser("en"))
        assert t.lang == "en"

    def test_unsupported_user_falls_back_to_en(self):
        self._mock_config_dir()
        t = get_user_translation(12372, FakeUser("fr"))
        assert t.lang == "en"

    def test_no_user_falls_back_to_en(self):
        """When user is None, default to 'en'."""
        t = get_user_translation(12373)
        assert t.lang == "en"


# ═══════════════════════ clear_user_lang_cache ════════════════════════


class TestClearUserLangCache:
    def _mock_config_dir(self) -> str:
        import config_manager  # noqa: PLC0415

        d = tempfile.mkdtemp()
        config_manager.DATA_DIR = d
        return d

    def test_purges_cache(self):
        self._mock_config_dir()

        # Populate cache
        detect_and_store_language(12380, FakeUser("ru"))
        assert get_user_language(12380) == "ru"

        # Clear
        clear_user_lang_cache()

        # After clearing cache and no user passed, detect_and_store will
        # read from config (which has 'ru') but get_user_language will
        # call detect_and_store which reads config
        lang = detect_and_store_language(12380)  # no user — should read from config
        assert lang == "ru"


# ═══════════════════════ Integration: full flow ═══════════════════════


class TestIntegrationFullFlow:
    """End-to-end: detection → storage → retrieval across sessions."""

    def _mock_config_dir(self) -> str:
        import config_manager  # noqa: PLC0415

        d = tempfile.mkdtemp()
        config_manager.DATA_DIR = d
        return d

    def setup_method(self):
        clear_cache()
        clear_user_lang_cache()

    def test_first_message_detects_and_stores(self):
        """First interaction detects RU, stores it, returns RU translations."""
        self._mock_config_dir()
        t = get_user_translation(12390, FakeUser("ru"))
        assert t.lang == "ru"
        assert t("start.welcome") != "?start.welcome?"

    def test_subsequent_messages_use_stored_lang(self):
        """After first detection, subsequent calls respect stored language."""
        data_dir = self._mock_config_dir()

        # "First" message: detect from user -> ru
        t1 = get_user_translation(12391, FakeUser("ru"))
        assert t1.lang == "ru"

        # Simulate bot restart: clear both caches
        clear_cache()
        clear_user_lang_cache()

        # "Second" message: should read 'ru' from config, not re-detect
        t2 = get_user_translation(12391)  # no user passed
        assert t2.lang == "ru"

    def test_persistence_across_bot_restarts(self):
        """Language persists in config file after simulated restart."""
        data_dir = self._mock_config_dir()

        # Session 1
        detect_and_store_language(12392, FakeUser("ru"))

        # Verify it's in the file
        path = os.path.join(data_dir, "12392.json")
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        assert config.get("language") == "ru"

        # "Restart" - fresh Python state
        clear_user_lang_cache()

        # Session 2 - should read from file
        lang = get_user_language(12392)
        assert lang == "ru"

    def test_config_and_language_coexist(self):
        """Language key coexists with existing config keys."""
        data_dir = self._mock_config_dir()

        # Pre-existing config with monitoring data
        path = os.path.join(data_dir, "12393.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "from_station": "Tbilisi",
                "to_station": "Batumi",
                "date": "2026-07-15",
                "seat_class": "Any",
            }, f)

        # Detect language
        lang = detect_and_store_language(12393, FakeUser("ru"))
        assert lang == "ru"

        # Verify config preserved
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        assert config["from_station"] == "Tbilisi"
        assert config["date"] == "2026-07-15"
        assert config["language"] == "ru"
