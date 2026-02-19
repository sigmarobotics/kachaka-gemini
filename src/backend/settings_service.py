import json
import os
from config import DATA_DIR, DEFAULT_SETTINGS

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _migrate(settings: dict) -> bool:
    """Migrate old single-mode keys to per-mode keys. Returns True if migrated."""
    changed = False

    if "gemini_model" in settings:
        old_model = settings.pop("gemini_model")
        api_mode = settings.get("api_mode", "text")
        if api_mode == "text":
            settings.setdefault("text_model", old_model)
        else:
            settings.setdefault("live_model", old_model)
        changed = True

    if "enable_google_search" in settings:
        old_val = settings.pop("enable_google_search")
        settings.setdefault("text_enable_google_search", old_val)
        settings.setdefault("live_enable_google_search", old_val)
        changed = True

    return changed


def get_all() -> dict:
    _ensure_dir()
    settings = DEFAULT_SETTINGS.copy()
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if _migrate(saved):
            merged = DEFAULT_SETTINGS.copy()
            merged.update(saved)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            return merged
        settings.update(saved)
    return settings


def get(key: str, default=None):
    return get_all().get(key, default)


def save(updates: dict):
    _ensure_dir()
    current = get_all()
    current.update(updates)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return current
