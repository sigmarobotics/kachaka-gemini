import json
import os
from config import DATA_DIR, DEFAULT_SETTINGS

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _migrate(settings: dict) -> bool:
    """Migrate old keys to new format. Returns True if migrated."""
    changed = False

    # gemini_model → per-mode keys
    if "gemini_model" in settings:
        old_model = settings.pop("gemini_model")
        api_mode = settings.get("api_mode", "text")
        if api_mode == "text":
            settings.setdefault("text_model", old_model)
        else:
            settings.setdefault("live_model", old_model)
        changed = True

    # enable_google_search → per-mode keys
    if "enable_google_search" in settings:
        old_val = settings.pop("enable_google_search")
        settings.setdefault("text_enable_google_search", old_val)
        settings.setdefault("live_enable_google_search", old_val)
        changed = True

    # drink_shelf_home → kiosk_location
    if "drink_shelf_home" in settings:
        old_val = settings.pop("drink_shelf_home")
        settings.setdefault("kiosk_location", old_val)
        changed = True

    # telegram_chat_id (string) → telegram_chat_ids (list)
    if "telegram_chat_id" in settings:
        old_val = settings.pop("telegram_chat_id")
        if old_val and "telegram_chat_ids" not in settings:
            settings["telegram_chat_ids"] = [old_val]
        changed = True

    # patrol_points: list of dicts → list of location ID strings
    if "patrol_points" in settings:
        pts = settings["patrol_points"]
        if pts and isinstance(pts, list) and len(pts) > 0 and isinstance(pts[0], dict):
            settings["patrol_points"] = [
                p.get("location_id", "") for p in pts if p.get("location_id")
            ]
            changed = True

    # function_declarations: if old FCs contain removed names, reset to defaults
    # Reset FCs to defaults if any new FCs are missing (e.g. after an update)
    if "function_declarations" in settings:
        from config import DEFAULT_FUNCTION_DECLARATIONS
        saved_names = {f.get("name") for f in settings["function_declarations"]}
        default_names = {f.get("name") for f in DEFAULT_FUNCTION_DECLARATIONS}
        if not default_names.issubset(saved_names):
            settings["function_declarations"] = DEFAULT_FUNCTION_DECLARATIONS
            changed = True

    # static_knowledge: reset if outdated (missing guide_to_booth rules)
    sk = settings.get("static_knowledge", "")
    if isinstance(sk, str) and sk and "guide_to_booth" not in sk:
        settings.pop("static_knowledge")
        changed = True

    # persona: reset if it references removed FCs
    persona_val = settings.get("persona", "")
    if isinstance(persona_val, str) and ("start_patrol" in persona_val
                                          or "deliver_drink" in persona_val):
        settings.pop("persona")
        changed = True

    # robot_background_info: reset if it doesn't contain the dynamic placeholder
    rbi = settings.get("robot_background_info", "")
    if isinstance(rbi, str) and rbi and "{{AVAILABLE_LOCATIONS}}" not in rbi:
        settings.pop("robot_background_info")
        changed = True

    # Remove deprecated keys
    deprecated_keys = [
        "shelf_ids", "patrol_model", "enable_interim_response",
        "interim_phrases", "interim_audio",
        "patrol_video_enable", "patrol_video_prompt",
    ]
    for key in deprecated_keys:
        if key in settings:
            settings.pop(key)
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
