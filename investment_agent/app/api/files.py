import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/files", tags=["files"])

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"

EXCLUDE = {".gitkeep", "agent.db"}
TEXT_EXTENSIONS = {".md", ".html", ".htm", ".txt", ".csv", ".json", ".xml", ".log", ".py", ".yaml", ".yml"}


def _safe_path(relative: str) -> Path:
    full = (DATA_DIR / relative).resolve()
    if not str(full).startswith(str(DATA_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    return full


def _scan_dir(directory: Path) -> list[dict]:
    """递归扫描目录（保留兼容旧接口）"""
    entries = []
    try:
        names = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return entries

    for p in names:
        if p.name in EXCLUDE:
            continue
        if p.is_dir():
            children = _scan_dir(p)
            entries.append({
                "name": p.name,
                "path": str(p.relative_to(DATA_DIR)),
                "type": "dir",
                "children": children,
            })
        else:
            entries.append({
                "name": p.name,
                "path": str(p.relative_to(DATA_DIR)),
                "type": "file",
                "size": p.stat().st_size,
                "ext": p.suffix.lower(),
            })
    return entries


def _list_dir(directory: Path) -> list[dict]:
    """只列出一层目录，子目录标记 hasChildren 供前端懒加载"""
    entries = []
    try:
        names = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return entries

    for p in names:
        if p.name in EXCLUDE:
            continue
        if p.is_dir():
            # 检查子目录是否有至少一个非排除项
            try:
                has_children = any(
                    c.name not in EXCLUDE
                    for c in p.iterdir()
                )
            except OSError:
                has_children = False
            entries.append({
                "name": p.name,
                "path": str(p.relative_to(DATA_DIR)),
                "type": "dir",
                "hasChildren": has_children,
            })
        else:
            entries.append({
                "name": p.name,
                "path": str(p.relative_to(DATA_DIR)),
                "type": "file",
                "size": p.stat().st_size,
                "ext": p.suffix.lower(),
            })
    return entries


@router.get("/tree")
async def file_tree():
    """递归返回整棵目录树（保留兼容，新前端建议用 /children）"""
    return _scan_dir(DATA_DIR)


@router.get("/children")
async def list_children(path: str = Query("", description="Relative path from data/ directory, empty for root")):
    """只返回指定目录的直接子节点，子目录附带 hasChildren 标记"""
    if path:
        dir_path = _safe_path(path)
    else:
        dir_path = DATA_DIR
    if not dir_path.exists() or not dir_path.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    return _list_dir(dir_path)


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
