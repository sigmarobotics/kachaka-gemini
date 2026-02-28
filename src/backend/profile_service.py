import json
import os
from config import DATA_DIR

PROFILES_DIR = os.path.join(DATA_DIR, "profiles")


def _ensure_dir():
    os.makedirs(PROFILES_DIR, exist_ok=True)


def list_profiles() -> list[str]:
    """Return sorted list of profile names (without .json extension)."""
    _ensure_dir()
    names = []
    for f in os.listdir(PROFILES_DIR):
        if f.endswith(".json"):
            names.append(f[:-5])
    return sorted(names)


def save_profile(name: str, settings: dict):
    """Save settings dict as a named profile."""
    _ensure_dir()
    path = os.path.join(PROFILES_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def load_profile(name: str) -> dict | None:
    """Load a profile by name. Returns None if not found."""
    path = os.path.join(PROFILES_DIR, f"{name}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_profile(name: str) -> bool:
    """Delete a profile. Returns True if deleted."""
    path = os.path.join(PROFILES_DIR, f"{name}.json")
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
