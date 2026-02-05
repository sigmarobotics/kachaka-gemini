import json
import os
from config import DATA_DIR, DEFAULT_SETTINGS

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def get_all() -> dict:
    _ensure_dir()
    settings = DEFAULT_SETTINGS.copy()
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
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
