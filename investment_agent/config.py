import json
import shutil
from pathlib import Path
from functools import lru_cache

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"


@lru_cache(maxsize=1)
def get_settings() -> dict:
    """读取 settings.json，带 LRU 缓存（maxsize=1 即可做刷新用）"""
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def reload_settings() -> dict:
    """清除缓存并重新读取配置"""
    get_settings.cache_clear()
    return get_settings()


def save_settings(data: dict) -> None:
    """写入 settings.json 并立即刷新缓存"""
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    get_settings.cache_clear()

