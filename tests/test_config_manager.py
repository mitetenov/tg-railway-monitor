"""Tests for config_manager.py"""
import os
import json
import tempfile
import sys

# Override DATA_DIR for tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config_manager as cm
from config_manager import DATA_DIR, is_config_complete


def setup_module():
    """Use a temp dir for test configs."""
    cm.DATA_DIR = tempfile.mkdtemp(prefix="tg_test_")
    cm._ensure_data_dir()


def teardown_module():
    """Clean up temp files."""
    import shutil
    shutil.rmtree(cm.DATA_DIR, ignore_errors=True)


def test_save_and_load():
    config = {"from_station": "Tbilisi", "to_station": "Batumi"}
    cm.save_config(12345, config)
    loaded = cm.load_config(12345)
    assert loaded == config


def test_load_nonexistent():
    loaded = cm.load_config(99999)
    assert loaded == {}


def test_delete_config(tmp_path):
    """Test delete removes the file."""
    chat_id = 11111
    cm.save_config(chat_id, {"test": True})
    path = cm._config_path(chat_id)
    assert os.path.exists(path)
    cm.delete_config(chat_id)
    assert not os.path.exists(path)


def test_is_config_complete():
    full = {
        "from_station_code": "56014",
        "to_station_code": "57151",
        "date": "2026-07-15",
        "seat_class": "Any",
    }
    assert is_config_complete(full)

    incomplete = {"from_station_code": "56014"}
    assert not is_config_complete(incomplete)

    empty = {}
    assert not is_config_complete(empty)


def test_overwrite_config():
    cm.save_config(22222, {"key": "old"})
    cm.save_config(22222, {"key": "new"})
    loaded = cm.load_config(22222)
    assert loaded["key"] == "new"


def test_unicode_in_config():
    config = {"from_station": "თბილისი", "to_station": "ბათუმი"}
    cm.save_config(33333, config)
    loaded = cm.load_config(33333)
    assert loaded["from_station"] == "თბილისი"
    assert loaded["to_station"] == "ბათუმი"
