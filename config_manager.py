"""
Per-chat configuration stored as individual JSON files.
Config: data/{chat_id}.json
State:  data/{chat_id}.state.json  (poller's last-seen seat counts)
"""
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

_STATE_SUFFIX = ".state.json"


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _config_path(chat_id: int) -> str:
    return os.path.join(DATA_DIR, f"{chat_id}.json")


def _state_path(chat_id: int) -> str:
    return os.path.join(DATA_DIR, f"{chat_id}{_STATE_SUFFIX}")


def iter_chat_ids() -> list[int]:
    """Return every chat id that has a stored configuration.

    Used at startup to restore monitoring after a restart.  State files
    (``{chat_id}.state.json``) are skipped — their stem is not numeric.
    """
    if not os.path.isdir(DATA_DIR):
        return []

    chat_ids = []
    for entry in os.listdir(DATA_DIR):
        if not entry.endswith(".json") or entry.endswith(_STATE_SUFFIX):
            continue
        stem = entry[: -len(".json")]
        try:
            chat_ids.append(int(stem))
        except ValueError:
            logger.warning("Skipping non-numeric config file: %s", entry)
    return sorted(chat_ids)


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
    """Remove config file for a chat (and its poller state)."""
    path = _config_path(chat_id)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            raise RuntimeError(
                f"Failed to delete config for chat {chat_id} at {path}: {e}"
            ) from e
    delete_state(chat_id)


# ── Poller state ─────────────────────────────────────────────────────
# Unlike the config, state is disposable: a read/write failure must never
# take the poller down, so these helpers log and degrade instead of
# raising.  Losing state costs one redundant notification, nothing more.


def load_state(chat_id: int) -> dict:
    """Load the poller's last-seen snapshot for a chat.

    Returns an empty dict if there is no state or it cannot be read.
    """
    path = _state_path(chat_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not load poller state for chat %d: %s", chat_id, e)
        return {}


def save_state(chat_id: int, state: dict) -> None:
    """Persist the poller's snapshot for a chat.

    Writes via a temporary file so an interrupted write cannot leave
    truncated JSON behind.
    """
    _ensure_data_dir()
    path = _state_path(chat_id)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("Could not save poller state for chat %d: %s", chat_id, e)
        try:
            os.remove(tmp)
        except OSError:
            pass


def delete_state(chat_id: int) -> None:
    """Remove the stored poller state for a chat, if any."""
    path = _state_path(chat_id)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            logger.warning("Could not delete poller state for chat %d: %s", chat_id, e)


def is_config_complete(config: dict) -> bool:
    """Check if all required fields are present for monitoring."""
    required = ("from_station_code", "to_station_code", "date", "seat_class")
    return all(k in config for k in required)
