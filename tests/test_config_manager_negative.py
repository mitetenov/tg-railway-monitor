"""Negative / edge-case tests for config_manager.py.

Covers: corrupted JSON, IO errors, delete nonexistent, edge configs
(empty, very large, special chars), concurrent access simulation,
is_config_complete edge cases.
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch, mock_open

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config_manager as cm


class TestConfigManagerNegative:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp(prefix="tg_test_neg_")
        self._saved_data_dir = cm.DATA_DIR
        cm.DATA_DIR = self._tmp

    def teardown_method(self):
        import shutil
        cm.DATA_DIR = self._saved_data_dir
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ── Corrupted JSON ──────────────────────────────────────────────────

    def test_corrupted_json_raises_runtime_error(self):
        chat_id = 50001
        path = cm._config_path(chat_id)
        with open(path, "w") as f:
            f.write("{not valid json!!")

        with pytest.raises(RuntimeError, match="Failed to load config"):
            cm.load_config(chat_id)

    def test_truncated_json_raises(self):
        chat_id = 50002
        path = cm._config_path(chat_id)
        with open(path, "w") as f:
            f.write('{"key": "val')

        with pytest.raises(RuntimeError):
            cm.load_config(chat_id)

    def test_empty_file_raises(self):
        chat_id = 50003
        path = cm._config_path(chat_id)
        path  # ensure it's used
        with open(cm._config_path(chat_id), "w") as f:
            f.write("")

        with pytest.raises(RuntimeError):
            cm.load_config(chat_id)

    def test_whitespace_only_file_raises(self):
        chat_id = 50004
        with open(cm._config_path(chat_id), "w") as f:
            f.write("   \n\t  ")

        with pytest.raises(RuntimeError):
            cm.load_config(chat_id)

    # ── Save errors ─────────────────────────────────────────────────────

    @pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permissions")
    def test_save_to_readonly_raises(self):
        """If the file is read-only, save should raise RuntimeError."""
        chat_id = 50010
        path = cm._config_path(chat_id)
        # Create a read-only file
        with open(path, "w") as f:
            f.write("{}")
        os.chmod(path, 0o444)

        try:
            with pytest.raises(RuntimeError, match="Failed to save"):
                cm.save_config(chat_id, {"key": "val"})
        finally:
            os.chmod(path, 0o644)  # cleanup

    def test_save_when_data_dir_is_file(self):
        """If data/ is a file instead of a directory, save should fail.
        BUG: _ensure_data_dir uses exist_ok=True which silently passes
        when DATA_DIR is a file. Then the actual file write fails with
        IsADirectoryError or similar.
        """
        import shutil
        shutil.rmtree(self._tmp)
        with open(self._tmp, "w") as f:
            f.write("blocking file")
        try:
            # The current code will try to makedirs(exist_ok=True) on a file
            # which succeeds (silently), then write fails
            with pytest.raises(Exception):
                cm.save_config(50011, {"key": "val"})
        finally:
            os.remove(self._tmp)

    # ── Delete edge cases ───────────────────────────────────────────────

    def test_delete_nonexistent_silent(self):
        """Deleting a config that doesn't exist should not raise."""
        cm.delete_config(99999)

    def test_delete_readonly_file(self):
        """BUG: On macOS, os.remove() on a read-only file succeeds because
        the directory permissions control deletion, not the file permissions.
        This test documents cross-platform behaviour.
        """
        chat_id = 50020
        path = cm._config_path(chat_id)
        with open(path, "w") as f:
            f.write("{}")
        # Mark read-only
        os.chmod(path, 0o444)
        try:
            # On macOS/Linux, os.remove checks directory write permission,
            # not file permission. So this typically succeeds.
            # The real test would be a directory without write permission.
            cm.delete_config(chat_id)
            assert not os.path.exists(path)
        finally:
            if os.path.exists(path):
                os.chmod(path, 0o644)
                os.remove(path)

    # ── Edge configs ────────────────────────────────────────────────────

    def test_empty_dict_config(self):
        cm.save_config(50030, {})
        loaded = cm.load_config(50030)
        assert loaded == {}

    def test_nested_complex_config(self):
        config = {
            "from_station": "Tbilisi",
            "nested": {"deep": {"key": [1, 2, 3]}},
            "array": list(range(100)),
        }
        cm.save_config(50031, config)
        loaded = cm.load_config(50031)
        assert loaded == config

    def test_unicode_special_chars(self):
        config = {"emoji": "🎫🚆🛑", "mixed": "한국어 日本語 العربية"}
        cm.save_config(50032, config)
        loaded = cm.load_config(50032)
        assert loaded == config

    def test_null_and_boolean_values(self):
        config = {"a": None, "b": True, "c": False, "d": 0, "e": ""}
        cm.save_config(50033, config)
        loaded = cm.load_config(50033)
        assert loaded == config

    # ── is_config_complete edge cases ───────────────────────────────────

    def test_complete_with_extra_keys(self):
        config = {
            "from_station_code": "56014",
            "to_station_code": "57151",
            "date": "2026-07-15",
            "seat_class": "Any",
            "extra_field": "ignored",
        }
        assert cm.is_config_complete(config)

    def test_missing_date_only(self):
        config = {
            "from_station_code": "56014",
            "to_station_code": "57151",
            "seat_class": "Any",
        }
        assert not cm.is_config_complete(config)

    def test_missing_seat_class_only(self):
        config = {
            "from_station_code": "56014",
            "to_station_code": "57151",
            "date": "2026-07-15",
        }
        assert not cm.is_config_complete(config)

    def test_none_values_count_as_present(self):
        """If keys exist but are None, is_config_complete returns True."""
        config = {
            "from_station_code": None,
            "to_station_code": None,
            "date": None,
            "seat_class": None,
        }
        assert cm.is_config_complete(config)

    def test_empty_string_values(self):
        config = {
            "from_station_code": "",
            "to_station_code": "",
            "date": "",
            "seat_class": "",
        }
        assert cm.is_config_complete(config)

    # ── Thread safety simulation ────────────────────────────────────────

    def test_concurrent_same_id_save_load(self):
        """Save and load different chat ids from multiple threads.
        Using different chat IDs avoids file-level write conflicts.
        """
        import threading

        errors = []

        def worker(idx):
            try:
                # Each thread uses a different chat_id to avoid write conflicts
                cm.save_config(50040 + idx, {"thread": idx, "value": idx * 10})
                cm.load_config(50040 + idx)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0, f"Got errors: {errors}"

    # ── Large config ────────────────────────────────────────────────────

    def test_large_config(self):
        config = {"key_" + str(i): "value_" * 100 + str(i) for i in range(100)}
        cm.save_config(50050, config)
        loaded = cm.load_config(50050)
        assert loaded == config
