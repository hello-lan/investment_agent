from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ...config import get_settings

router = APIRouter(prefix="/api/files", tags=["files"])

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"

_DEFAULT_EXCLUDE = [".gitkeep", "agent.db"]
TEXT_EXTENSIONS = {".md", ".html", ".htm", ".txt", ".csv", ".json", ".xml", ".log", ".py", ".yaml", ".yml"}


def _safe_path(relative: str) -> Path:
    full = (DATA_DIR / relative).resolve()
    if not str(full).startswith(str(DATA_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    return full


def _normalize_rel(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/")


def _pattern_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    patterns = []
    for item in value:
        norm = _normalize_rel(str(item))
        if norm:
            patterns.append(norm)
    return patterns


def _file_browser_rules() -> tuple[list[str], list[str]]:
    """读取 file_browser.include / exclude。缺省整段配置时仍排除 .gitkeep 与 agent.db。"""
    try:
        settings = get_settings()
    except (OSError, ValueError, TypeError):
        return [], list(_DEFAULT_EXCLUDE)
    cfg = settings.get("file_browser") if isinstance(settings, dict) else None
    if not isinstance(cfg, dict):
        return [], list(_DEFAULT_EXCLUDE)
    include = _pattern_list(cfg.get("include"))
    if "exclude" in cfg:
        exclude = _pattern_list(cfg.get("exclude"))
    else:
        exclude = list(_DEFAULT_EXCLUDE)
    return include, exclude


def _is_excluded(rel: str, exclude: list[str]) -> bool:
    rel = _normalize_rel(rel)
    if not rel:
        return False
    parts = rel.split("/")
    for pat in exclude:
        if "/" not in pat:
            if pat in parts:
                return True
        elif rel == pat or rel.startswith(pat + "/"):
            return True
    return False


def _is_included(rel: str, include: list[str]) -> bool:
    """include 为空表示不限制。目录包含其下全部内容，更深路径的祖先目录也可见。"""
    if not include:
        return True
    rel = _normalize_rel(rel)
    if not rel:
        return True
    for pat in include:
        if rel == pat or rel.startswith(pat + "/"):
            return True
        if pat.startswith(rel + "/"):
            return True
    return False


def _is_visible(rel: str, include: list[str], exclude: list[str]) -> bool:
    rel = _normalize_rel(rel)
    if not rel:
        return True
    return _is_included(rel, include) and not _is_excluded(rel, exclude)


def _rel_to_data(path: Path) -> str:
    return path.resolve().relative_to(DATA_DIR.resolve()).as_posix()


def _has_visible_children(directory: Path, include: list[str], exclude: list[str]) -> bool:
    try:
        children = list(directory.iterdir())
    except OSError:
        return False
    for child in children:
        if _is_visible(_rel_to_data(child), include, exclude):
            return True
    return False


def _scan_dir(directory: Path, include: list[str], exclude: list[str]) -> list[dict]:
    """递归扫描目录（保留兼容旧接口）"""
    entries = []
    try:
        names = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return entries

    for p in names:
        rel = _rel_to_data(p)
        if not _is_visible(rel, include, exclude):
            continue
        if p.is_dir():
            children = _scan_dir(p, include, exclude)
            entries.append({
                "name": p.name,
                "path": rel,
                "type": "dir",
                "children": children,
            })
        else:
            entries.append({
                "name": p.name,
                "path": rel,
                "type": "file",
                "size": p.stat().st_size,
                "ext": p.suffix.lower(),
            })
    return entries


def _list_dir(directory: Path, include: list[str], exclude: list[str]) -> list[dict]:
    """只列出一层目录，子目录标记 hasChildren 供前端懒加载"""
    entries = []
    try:
        names = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return entries

    for p in names:
        rel = _rel_to_data(p)
        if not _is_visible(rel, include, exclude):
            continue
        if p.is_dir():
            entries.append({
                "name": p.name,
                "path": rel,
                "type": "dir",
                "hasChildren": _has_visible_children(p, include, exclude),
            })
        else:
            entries.append({
                "name": p.name,
                "path": rel,
                "type": "file",
                "size": p.stat().st_size,
                "ext": p.suffix.lower(),
            })
    return entries


@router.get("/tree")
async def file_tree():
    """递归返回整棵目录树（保留兼容，新前端建议用 /children）"""
    include, exclude = _file_browser_rules()
    return _scan_dir(DATA_DIR, include, exclude)


@router.get("/children")
async def list_children(path: str = Query("", description="Relative path from data/ directory, empty for root")):
    """只返回指定目录的直接子节点，子目录附带 hasChildren 标记"""
    if path:
        dir_path = _safe_path(path)
    else:
        dir_path = DATA_DIR
    if not dir_path.exists() or not dir_path.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    include, exclude = _file_browser_rules()
    rel = "" if dir_path.resolve() == DATA_DIR.resolve() else _rel_to_data(dir_path)
    if not _is_visible(rel, include, exclude):
        raise HTTPException(status_code=404, detail="Directory not found")
    return _list_dir(dir_path, include, exclude)


@router.get("/view")
async def view_file(path: str = Query(..., description="Relative path from data/ directory")):
    file_path = _safe_path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return {
            "type": "pdf",
            "name": file_path.name,
            "url": f"/data-files/{path}",
            "size": file_path.stat().st_size,
        }

    if ext in TEXT_EXTENSIONS:
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file_path.read_text(encoding="gbk", errors="replace")
        return {
            "type": "text",
            "name": file_path.name,
            "ext": ext,
            "content": content,
            "size": file_path.stat().st_size,
        }

    return {
        "type": "binary",
        "name": file_path.name,
        "url": f"/data-files/{path}",
        "size": file_path.stat().st_size,
    }
