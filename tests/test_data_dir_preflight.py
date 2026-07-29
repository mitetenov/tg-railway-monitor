"""Startup preflight for the data directory.

A Docker volume whose files belong to a different uid than the container
runs as makes every config write fail. Without a preflight that surfaces
as a traceback on every single user message, with no hint of the cause —
which is exactly how it showed up in production after the uid changed.
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config_manager
from config_manager import check_data_dir_writable


class TestWritableDataDir:

    def test_reports_ok_for_a_writable_dir(self, tmp_path):
        with patch.object(config_manager, "DATA_DIR", str(tmp_path)):
            ok, message = check_data_dir_writable()
        assert ok
        assert message == ""

    def test_creates_the_dir_when_missing(self, tmp_path):
        target = tmp_path / "not-there-yet"
        with patch.object(config_manager, "DATA_DIR", str(target)):
            ok, _ = check_data_dir_writable()
        assert ok
        assert target.is_dir()

    def test_leaves_no_probe_file_behind(self, tmp_path):
        with patch.object(config_manager, "DATA_DIR", str(tmp_path)):
            check_data_dir_writable()
        assert list(tmp_path.iterdir()) == []

    def test_does_not_disturb_existing_files(self, tmp_path):
        (tmp_path / "42.json").write_text("{}")
        with patch.object(config_manager, "DATA_DIR", str(tmp_path)):
            ok, _ = check_data_dir_writable()
        assert ok
        assert (tmp_path / "42.json").read_text() == "{}"


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file permissions")
class TestUnwritableDataDir:

    def test_reports_failure(self, tmp_path):
        target = tmp_path / "locked"
        target.mkdir()
        target.chmod(0o500)  # r-x: listable, not writable
        try:
            with patch.object(config_manager, "DATA_DIR", str(target)):
                ok, message = check_data_dir_writable()
        finally:
            target.chmod(0o700)
        assert not ok
        assert message

    def test_message_names_both_uids_and_the_fix(self, tmp_path):
        """The operator must be able to act on the message alone."""
        target = tmp_path / "locked"
        target.mkdir()
        target.chmod(0o500)
        try:
            with patch.object(config_manager, "DATA_DIR", str(target)):
                _, message = check_data_dir_writable()
        finally:
            target.chmod(0o700)

        assert str(target) in message, "must say which directory"
        assert f"uid {os.getuid()}" in message, "must say what uid we run as"
        assert "chown" in message, "must give the remedy"

    def test_never_raises(self, tmp_path):
        """Preflight is diagnostic: it must not itself take startup down."""
        target = tmp_path / "locked"
        target.mkdir()
        target.chmod(0o500)
        try:
            with patch.object(config_manager, "DATA_DIR", str(target)):
                check_data_dir_writable()  # must not raise
        finally:
            target.chmod(0o700)
