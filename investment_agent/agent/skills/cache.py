"""Skill body 缓存层：TTL 惰性过期 + references/assets 内存加载。

不启动后台线程。过期检查在 get() 时惰性执行。
"""

import time
from pathlib import Path

from .markdown_parser import load_skill_body


class CacheEntry:
    """单个缓存条目"""
    __slots__ = ("body", "refs", "loaded_at", "last_access")

    def __init__(self, body: str, refs: dict[str, bytes] | None = None):
        self.body = body
        self.refs = refs or {}
        self.loaded_at = time.time()
        self.last_access = self.loaded_at

    def touch(self) -> None:
        self.last_access = time.time()

    def is_expired(self, ttl: int) -> bool:
        return (time.time() - self.last_access) > ttl


class SkillCache:
    """Skill body 缓存单例。

    TTL 默认 600 秒，可通过 settings.json 的 engine.skill_body_ttl 覆盖。
    """

    def __init__(self):
        self._entries: dict[str, CacheEntry] = {}
        self._ttl: int = 600

    def set_ttl(self, seconds: int) -> None:
        self._ttl = seconds

    def _load_refs(self, skill_dir: Path) -> dict[str, bytes]:
        """加载 references/ 和 assets/ 目录下的文件内容到内存。
        不返回给 LLM——仅预加载，LLM 请求时再展示。
        """
        refs: dict[str, bytes] = {}
        for sub in ("references", "assets"):
            sub_dir = skill_dir / sub
            if not sub_dir.is_dir():
                continue
            for f in sub_dir.rglob("*"):
                if f.is_file():
                    try:
                        refs[str(f.relative_to(skill_dir))] = f.read_bytes()
                    except Exception:
                        continue
        return refs

    def get(self, name: str, md_path: Path, skill_dir: Path) -> str:
        """获取 Skill body。缓存命中且未过期则直接返回；否则从文件加载。"""
        entry = self._entries.get(name)
        if entry is not None and not entry.is_expired(self._ttl):
            entry.touch()
            return entry.body

        # miss 或过期：重新加载
        body = load_skill_body(md_path)
        refs = self._load_refs(skill_dir)
        new_entry = CacheEntry(body, refs)
        self._entries[name] = new_entry
        return body

    def get_refs(self, name: str) -> dict[str, bytes]:
        """获取已缓存的 references/assets 内容。调用者应在 get() 之后调用。"""
        entry = self._entries.get(name)
        return entry.refs if entry else {}

    def invalidate(self, name: str) -> None:
        self._entries.pop(name, None)

    def cleanup(self) -> int:
        """惰性清理所有过期条目，返回清理数量。"""
        expired = [n for n, e in self._entries.items() if e.is_expired(self._ttl)]
        for n in expired:
            del self._entries[n]
        return len(expired)


# 全局单例
_cache = SkillCache()


def get_cache() -> SkillCache:
    return _cache
