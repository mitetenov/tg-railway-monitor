"""
Per-chat configuration stored as individual JSON files.
Config: data/{chat_id}.json
State:  data/{chat_id}.state.json  (poller's last-seen seat counts)
"""
import json
import logging
import os
import tempfile
from typing import Optional

from monitor_config import ConfigValidationError, MonitorConfig

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

_STATE_SUFFIX = ".state.json"


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def check_data_dir_writable() -> tuple[bool, str]:
    """Verify the data directory can actually be written to.

    Called once at startup so an unwritable volume is reported as a single
    clear message rather than a stack trace on every user interaction —
    the usual cause is a volume whose files are owned by a different uid
    than the one the container runs as.

    Returns ``(ok, message)``; *message* is only meaningful when not ok.
    """
    probe = os.path.join(DATA_DIR, ".write-probe")
    try:
        _ensure_data_dir()
        with open(probe, "w", encoding="utf-8") as f:
            f.write("")
        os.remove(probe)
        return (True, "")
    except OSError as e:
        try:
            owner = os.stat(DATA_DIR).st_uid
        except OSError:
            owner = "?"
        return (
            False,
            f"{DATA_DIR} is not writable ({e}). "
            f"The container runs as uid {os.getuid()} but the directory is "
            f"owned by uid {owner}. If this is a Docker volume from an "
            f"earlier image, fix it with:\n"
            f"  docker run --rm -v <volume>:/data alpine "
            f"chown -R {os.getuid()}:{os.getuid()} /data",
        )


def _config_path(chat_id: int) -> str:
    return os.path.join(DATA_DIR, f"{chat_id}.json")


def _atomic_write_json(path: str, data: dict) -> None:
    """Atomically replace *path* with JSON data on the same filesystem."""
    _ensure_data_dir()
    descriptor, temporary_path = tempfile.mkstemp(
        dir=DATA_DIR,
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError:
        try:
            os.remove(temporary_path)
        except OSError:
            pass
        raise


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
            config = json.load(f)
        if not isinstance(config, dict):
            raise RuntimeError(
                f"Failed to load config for chat {chat_id} from {path}: "
                "root value must be a JSON object"
            )
        return config
    except (json.JSONDecodeError, IOError, OSError) as e:
        raise RuntimeError(
            f"Failed to load config for chat {chat_id} from {path}: {e}"
        ) from e


def save_config(chat_id: int, config: dict) -> None:
    """Persist config dict for a chat."""
    path = _config_path(chat_id)
    try:
        _atomic_write_json(path, config)
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


def clear_monitor_config(chat_id: int) -> None:
    """Remove monitor settings and state while preserving interface language."""
    try:
        config = load_config(chat_id)
    except RuntimeError as error:
        logger.warning("Removing unreadable config for chat %d: %s", chat_id, error)
        delete_config(chat_id)
        return
    language = config.get("language")
    if language:
        save_config(chat_id, {"language": language})
    else:
        delete_config(chat_id)
        return
    delete_state(chat_id)


def load_monitor_config(chat_id: int) -> MonitorConfig:
    """Load and validate a complete monitor configuration."""
    return MonitorConfig.from_dict(load_config(chat_id))


def save_monitor_config(
    chat_id: int,
    config: MonitorConfig,
    language: Optional[str] = None,
) -> None:
    """Persist validated monitoring fields and an optional UI language."""
    data = config.to_dict()
    if language:
        data["language"] = language
    save_config(chat_id, data)


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
    path = _state_path(chat_id)
    try:
        _atomic_write_json(path, state)
    except OSError as e:
        logger.warning("Could not save poller state for chat %d: %s", chat_id, e)


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
    try:
        MonitorConfig.from_dict(config)
    except ConfigValidationError:
        return False
    return True
