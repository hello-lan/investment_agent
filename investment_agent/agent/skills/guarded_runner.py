"""带 write-guard 的 Python 脚本启动器。

由 script_runner 以子进程方式调用：
  python guarded_runner.py <script.py> [argv...]

环境变量：
  IA_DATA_ROOT     — 唯一允许写入的根目录（通常为项目 data/）
  IA_PROJECT_ROOT  — 项目根（用于相对路径解析）
"""

from __future__ import annotations

import builtins
import os
import runpy
import sys
from pathlib import Path


_WRITE_MODES = frozenset("wax+")


def _is_write_mode(mode: str | None) -> bool:
    if not mode:
        return False
    # 文本/二进制写、追加、独占创建
    return any(ch in mode for ch in ("w", "a", "x", "+"))


def install_write_guard(data_root: Path, project_root: Path | None = None) -> None:
    """安装 builtins.open / Path 写操作守卫。

    允许：
    - data_root 及其子路径
    - 系统临时目录（tempfile / TMP / TEMP）
    拒绝：
    - 项目根内、但不在 data_root 下的路径（extensions/ 只读等）
    """
    import tempfile

    data_root = data_root.resolve()
    project_root = (
        Path(project_root).resolve()
        if project_root
        else Path(os.environ.get("IA_PROJECT_ROOT", data_root.parent)).resolve()
    )
    temp_roots = [
        Path(tempfile.gettempdir()).resolve(),
    ]
    for key in ("TMP", "TEMP", "TMPDIR"):
        raw = os.environ.get(key, "").strip()
        if raw:
            try:
                temp_roots.append(Path(raw).resolve())
            except OSError:
                pass

    orig_open = builtins.open

    def _is_under(root: Path, path: Path) -> bool:
        return path == root or root in path.parents

    def _ensure_writable(path_like: object) -> Path:
        path = Path(os.fspath(path_like)).resolve()
        if _is_under(data_root, path):
            return path
        if any(_is_under(root, path) for root in temp_roots):
            return path
        # 项目内非 data 写入一律拒绝（extensions / 源码等）
        if _is_under(project_root, path):
            raise PermissionError(
                f"写入被拒绝：项目内仅允许写入 data/，收到 {path}"
            )
        # 项目外其它路径默认拒绝，避免任意落盘
        raise PermissionError(
            f"写入被拒绝：路径必须位于 data/ 或系统临时目录，收到 {path}"
        )

    def guarded_open(file, mode="r", *args, **kwargs):
        if _is_write_mode(str(mode)):
            _ensure_writable(file)
        return orig_open(file, mode, *args, **kwargs)

    builtins.open = guarded_open  # type: ignore[assignment]

    # Path.write_text / write_bytes / open / touch / mkdir / replace / unlink
    _orig_path_open = Path.open
    _orig_write_text = Path.write_text
    _orig_write_bytes = Path.write_bytes
    _orig_touch = Path.touch
    _orig_mkdir = Path.mkdir
    _orig_replace = Path.replace
    _orig_rename = Path.rename
    _orig_unlink = Path.unlink
    _orig_rmdir = Path.rmdir

    def path_open(self, mode="r", *args, **kwargs):
        if _is_write_mode(str(mode)):
            _ensure_writable(self)
        return _orig_path_open(self, mode, *args, **kwargs)

    def path_write_text(self, data, *args, **kwargs):
        _ensure_writable(self)
        return _orig_write_text(self, data, *args, **kwargs)

    def path_write_bytes(self, data, *args, **kwargs):
        _ensure_writable(self)
        return _orig_write_bytes(self, data, *args, **kwargs)

    def path_touch(self, *args, **kwargs):
        _ensure_writable(self)
        return _orig_touch(self, *args, **kwargs)

    def path_mkdir(self, *args, **kwargs):
        _ensure_writable(self)
        return _orig_mkdir(self, *args, **kwargs)

    def path_replace(self, target):
        _ensure_writable(self)
        _ensure_writable(target)
        return _orig_replace(self, target)

    def path_rename(self, target):
        _ensure_writable(self)
        _ensure_writable(target)
        return _orig_rename(self, target)

    def path_unlink(self, *args, **kwargs):
        _ensure_writable(self)
        return _orig_unlink(self, *args, **kwargs)

    def path_rmdir(self):
        _ensure_writable(self)
        return _orig_rmdir(self)

    Path.open = path_open  # type: ignore[method-assign, assignment]
    Path.write_text = path_write_text  # type: ignore[method-assign, assignment]
    Path.write_bytes = path_write_bytes  # type: ignore[method-assign, assignment]
    Path.touch = path_touch  # type: ignore[method-assign, assignment]
    Path.mkdir = path_mkdir  # type: ignore[method-assign, assignment]
    Path.replace = path_replace  # type: ignore[method-assign, assignment]
    Path.rename = path_rename  # type: ignore[method-assign, assignment]
    Path.unlink = path_unlink  # type: ignore[method-assign, assignment]
    Path.rmdir = path_rmdir  # type: ignore[method-assign, assignment]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: guarded_runner.py <script.py> [args...]", file=sys.stderr)
        return 2

    data_root = os.environ.get("IA_DATA_ROOT", "").strip()
    if not data_root:
        print("IA_DATA_ROOT is required", file=sys.stderr)
        return 2

    project_root = os.environ.get("IA_PROJECT_ROOT", "").strip() or None
    install_write_guard(Path(data_root), Path(project_root) if project_root else None)

    script = Path(argv[0]).resolve()
    if script.suffix != ".py" or not script.is_file():
        print(f"invalid script: {argv[0]}", file=sys.stderr)
        return 2

    # 对齐 `python script.py`：把脚本所在目录放到 sys.path[0]，
    # 否则 runpy.run_path 无法解析脚本旁相对导入（如 from sources import ...）
    script_dir = str(script.parent)
    if sys.path and sys.path[0] == script_dir:
        pass
    else:
        # 去掉空 cwd 占位，避免遮蔽脚本目录
        while sys.path and sys.path[0] in ("", "."):
            sys.path.pop(0)
        if script_dir in sys.path:
            sys.path.remove(script_dir)
        sys.path.insert(0, script_dir)

    sys.argv = [str(script), *argv[1:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
