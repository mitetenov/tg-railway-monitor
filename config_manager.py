"""
Per-chat configuration stored as individual JSON files.
File: data/{chat_id}.json
"""
import json
import os
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _config_path(chat_id: int) -> str:
    return os.path.join(DATA_DIR, f"{chat_id}.json")


def load_config(chat_id: int) -> dict:
    """Load config dict for a chat. Returns empty dict if none exists."""
    path = _config_path(chat_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError, OSError) as e:
        raise RuntimeError(
            f"Failed to load config for chat {chat_id} from {path}: {e}"
        ) from e


def save_config(chat_id: int, config: dict) -> None:
    """Persist config dict for a chat."""
    _ensure_data_dir()
    path = _config_path(chat_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except (IOError, OSError) as e:
        raise RuntimeError(
            f"Failed to save config for chat {chat_id} to {path}: {e}"
        ) from e


def delete_config(chat_id: int) -> None:
    """Remove config file for a chat."""
    path = _config_path(chat_id)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            raise RuntimeError(
                f"Failed to delete config for chat {chat_id} at {path}: {e}"
            ) from e


def is_config_complete(config: dict) -> bool:
    """Check if all required fields are present for monitoring."""
    required = ("from_station_code", "to_station_code", "date", "seat_class")
    return all(k in config for k in required)
