import json
import shutil
from pathlib import Path
from functools import lru_cache

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"
LEGACY_SETTINGS_PATH = PROJECT_ROOT / "settings.json"


def _migrate_legacy_settings_if_needed() -> None:
    if SETTINGS_PATH.exists() or not LEGACY_SETTINGS_PATH.exists():
        return
    shutil.move(str(LEGACY_SETTINGS_PATH), str(SETTINGS_PATH))


@lru_cache(maxsize=1)
def get_settings() -> dict:
    _migrate_legacy_settings_if_needed()
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def reload_settings() -> dict:
    get_settings.cache_clear()
    return get_settings()


def save_settings(data: dict) -> None:
    _migrate_legacy_settings_if_needed()
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    get_settings.cache_clear()

