"""Skill / run_python_script 共用的 Python 脚本执行器。"""

from __future__ import annotations

import asyncio
import json
import locale
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_GUARDED_RUNNER = Path(__file__).resolve().parent / "guarded_runner.py"

_WRITE_CLI_FLAGS = frozenset({
    "-o", "--output", "--out", "--outfile",
    "--save-dir", "--save_dir", "--dest", "--output-path", "--output_path",
})
_WRITE_KWARG_KEYS = frozenset({
    "output", "out", "outfile", "save_dir", "dest", "output_path",
})


def _ensure_subpath(base: Path, target: Path) -> None:
    """安全检查：确保入口脚本不逃逸 Skill 目录（防止路径穿越攻击）。"""
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if target_resolved != base_resolved and base_resolved not in target_resolved.parents:
        raise ValueError(f"entry path escapes skill dir: {target}")


def _kwargs_to_cli(kwargs: dict) -> list[str]:
    """将 Python kwargs 转为 CLI 参数列表：{"foo_bar": "val"} → ["--foo-bar", "val"]"""
    cli_args: list[str] = []
    for key, value in kwargs.items():
        flag = "--" + key.replace("_", "-")
        if value is None:
            continue
        if isinstance(value, bool):
            if value:
                cli_args.append(flag)
        else:
            cli_args.append(flag)
            cli_args.append(str(value))
    return cli_args


def _decode_output(data: bytes | None) -> str:
    if not data:
        return ""
    for encoding in (
        "utf-8",
        locale.getpreferredencoding(False) or "gbk",
        "gbk",
    ):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _subprocess_env(project_root: Path, data_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["IA_PROJECT_ROOT"] = str(project_root)
    env["IA_DATA_ROOT"] = str(data_root)
    if sys.platform == "win32":
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
    return env


def _looks_like_path(value: str) -> bool:
    if not value or value.startswith("-"):
        return False
    if "/" in value or "\\" in value:
        return True
    lower = value.lower()
    return lower.endswith((
        ".py", ".md", ".json", ".pdf", ".txt", ".csv", ".xlsx", ".html", ".xml",
    ))


_FORBIDDEN_WRITE_TOP = frozenset({
    "extensions", "investment_agent", ".git", ".claude", ".venv", ".venv_2",
    "__pycache__",
})


def _assert_write_under_data(
    raw: str,
    *,
    project_root: Path,
    data_root: Path,
) -> None:
    path = Path(raw)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        top = path.parts[0] if path.parts else ""
        # 明确指向非 data 顶层目录的路径一律拒绝（禁止悄悄 remap 到 data/ 下）
        if top in _FORBIDDEN_WRITE_TOP:
            raise ValueError(f"输出路径必须位于 data/ 内: {raw}")
        if path.parent == Path(".") and path.name == raw:
            resolved = (data_root / "tmp" / path).resolve()
        elif top == "data":
            resolved = (project_root / path).resolve()
        else:
            resolved = (data_root / path).resolve()

    if resolved != data_root and data_root not in resolved.parents:
        raise ValueError(f"输出路径必须位于 data/ 内: {raw}")


def precheck_output_paths(
    *,
    project_root: Path | str,
    argv: list[str] | None = None,
    kwargs: dict[str, Any] | None = None,
) -> None:
    """对明显写目标参数做预检：必须落在 data/ 下。"""
    project_root = Path(project_root).resolve()
    data_root = (project_root / "data").resolve()

    if kwargs:
        for key, value in kwargs.items():
            if key not in _WRITE_KWARG_KEYS:
                continue
            if isinstance(value, str) and _looks_like_path(value):
                _assert_write_under_data(
                    value, project_root=project_root, data_root=data_root,
                )

    if not argv:
        return

    expect_write = False
    for token in argv:
        if expect_write:
            if isinstance(token, str) and _looks_like_path(token):
                _assert_write_under_data(
                    token, project_root=project_root, data_root=data_root,
                )
            expect_write = False
            continue
        if token in _WRITE_CLI_FLAGS:
            expect_write = True
            continue
        # --output=path 形式
        for flag in _WRITE_CLI_FLAGS:
            prefix = flag + "="
            if token.startswith(prefix):
                raw = token[len(prefix):]
                if _looks_like_path(raw):
                    _assert_write_under_data(
                        raw, project_root=project_root, data_root=data_root,
                    )
                break


def _run_python_sync(
    *,
    project_root: Path,
    entry_path: Path,
    cli_args: list[str],
    stdin_text: str | None,
    timeout_seconds: int,
) -> str:
    """在工作线程中同步执行（避免 Windows SelectorEventLoop 不支持 asyncio subprocess）。"""
    data_root = (project_root / "data").resolve()
    data_root.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(_GUARDED_RUNNER),
        str(entry_path),
        *cli_args,
    ]
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": str(project_root),
        "env": _subprocess_env(project_root, data_root),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    stdin_bytes = None if stdin_text is None else stdin_text.encode("utf-8")
    if stdin_bytes is not None:
        kwargs["stdin"] = subprocess.PIPE

    proc = subprocess.Popen(cmd, **kwargs)
    try:
        stdout, stderr = proc.communicate(input=stdin_bytes, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        raise RuntimeError(f"script timed out after {timeout_seconds}s") from None

    stdout_text = _decode_output(stdout)
    stderr_text = _decode_output(stderr)

    if proc.returncode != 0:
        err = (stderr_text or stdout_text or "script failed").strip()
        raise RuntimeError(err)

    result = stdout_text.strip()
    if stderr_text.strip():
        # 非零已上面处理；零退出码时附带 stderr 便于诊断
        if result:
            result = f"{result}\n{stderr_text.strip()}"
        else:
            result = stderr_text.strip()
    return result


async def run_python_entry(
    *,
    project_root: Path | str,
    entry_path: Path | str,
    skill_root: Path | str | None = None,
    argv: list[str] | None = None,
    kwargs: dict[str, Any] | None = None,
    stdin: str | None = None,
    timeout_seconds: int = 120,
    use_write_guard: bool = True,
) -> str:
    """在项目根 cwd 下执行已校验的 Python 脚本。

    Args:
        project_root: 项目根（cwd）
        entry_path: 脚本绝对或相对路径
        skill_root: 若提供，校验脚本必须在该 skill 目录内
        argv: 位置参数 / 子命令（优先）
        kwargs: 转为 --flag 追加在 argv 后；若未提供 stdin 则以 JSON 写入 stdin
        stdin: 显式 stdin；为 None 且有 kwargs 时默认传 JSON kwargs
        timeout_seconds: 超时秒数
        use_write_guard: 是否经 guarded_runner 启动（默认 True）
    """
    project_root = Path(project_root).resolve()
    entry_path = Path(entry_path)
    if not entry_path.is_absolute():
        entry_path = (project_root / entry_path).resolve()
    else:
        entry_path = entry_path.resolve()

    if skill_root is not None:
        _ensure_subpath(Path(skill_root), entry_path)

    if entry_path.suffix != ".py":
        raise ValueError(f"only python entry is supported: {entry_path}")
    if not entry_path.exists() or not entry_path.is_file():
        raise ValueError(f"entry file not found: {entry_path}")

    argv = list(argv or [])
    kwargs = dict(kwargs or {})
    precheck_output_paths(project_root=project_root, argv=argv, kwargs=kwargs)

    cli_args = [*argv, *_kwargs_to_cli(kwargs)]
    if stdin is None and kwargs:
        stdin_text = json.dumps(kwargs, ensure_ascii=False)
    else:
        stdin_text = stdin

    if not use_write_guard:
        # 兼容路径：直接 exec（无 write-guard）
        return await asyncio.to_thread(
            _run_python_direct_sync,
            project_root=project_root,
            entry_path=entry_path,
            cli_args=cli_args,
            stdin_text=stdin_text,
            timeout_seconds=timeout_seconds,
        )

    return await asyncio.to_thread(
        _run_python_sync,
        project_root=project_root,
        entry_path=entry_path,
        cli_args=cli_args,
        stdin_text=stdin_text,
        timeout_seconds=timeout_seconds,
    )


def _run_python_direct_sync(
    *,
    project_root: Path,
    entry_path: Path,
    cli_args: list[str],
    stdin_text: str | None,
    timeout_seconds: int,
) -> str:
    data_root = (project_root / "data").resolve()
    cmd = [sys.executable, str(entry_path), *cli_args]
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": str(project_root),
        "env": _subprocess_env(project_root, data_root),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    stdin_bytes = None if stdin_text is None else stdin_text.encode("utf-8")
    if stdin_bytes is not None:
        kwargs["stdin"] = subprocess.PIPE

    proc = subprocess.Popen(cmd, **kwargs)
    try:
        stdout, stderr = proc.communicate(input=stdin_bytes, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        raise RuntimeError(f"script timed out after {timeout_seconds}s") from None

    stdout_text = _decode_output(stdout)
    stderr_text = _decode_output(stderr)
    if proc.returncode != 0:
        raise RuntimeError((stderr_text or stdout_text or "script failed").strip())
    return stdout_text.strip()


async def run_skill_entry(
    skill_dir: Path,
    entry: str,
    kwargs: dict,
    timeout_seconds: int = 20,
) -> str:
    """通过子进程执行 Skill 的 Python 入口脚本（MarkdownSkill.entry 兼容入口）。

    cwd 为项目根；脚本路径相对 skill_dir；仍走 write-guard。
    """
    skill_dir = Path(skill_dir).resolve()
    entry_path = (skill_dir / entry).resolve()
    _ensure_subpath(skill_dir, entry_path)

    # skill_dir = .../extensions/skills/<name> → 上溯 4 层到项目根
    # skills/<name> ← skills ← extensions ← project_root
    project_root = skill_dir.parents[2] if len(skill_dir.parents) >= 3 else skill_dir

    return await run_python_entry(
        project_root=project_root,
        entry_path=entry_path,
        skill_root=skill_dir,
        kwargs=kwargs,
        timeout_seconds=timeout_seconds,
    )
