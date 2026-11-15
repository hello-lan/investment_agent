import json
import os
import shutil
from pathlib import Path
from functools import lru_cache

ROOT_DIR = Path(__file__).resolve().parent.parent
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


def resolve_skills_dir(raw_dir: str | None = None) -> Path:
    """解析 Skills 目录路径（支持相对路径，相对于项目根目录）。"""
    if raw_dir is None:
        skills_cfg = get_settings().get("skills", {})
        if not isinstance(skills_cfg, dict):
            skills_cfg = {}
        raw_dir = str(skills_cfg.get("directory", "./skills")).strip() or "./skills"
    path = Path(raw_dir)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def get_tushare_token() -> str:
    """读取 tushare token，环境变量优先于 settings.json。"""
    env_token = os.getenv("TUSHARE_TOKEN", "").strip()
    if env_token:
        return env_token
    return str(get_settings().get("tools", {}).get("tushare_token", "") or "").strip()

