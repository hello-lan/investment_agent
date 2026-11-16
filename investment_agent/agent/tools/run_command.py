from __future__ import annotations

import asyncio
import locale
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from .access_policy import AccessPolicy
from .base import BaseTool

# 项目根目录，由 app 层在启动时注入
_project_root: str | None = None

_COMMAND_TIMEOUT = 120


def set_project_root(path: str) -> None:
    global _project_root
    _project_root = path


@lru_cache(maxsize=1)
def _resolve_shell() -> tuple[str, str | None]:
    """解析当前平台应使用的 shell。

    Returns:
        (mode, bash_path):
          - ("bash", path)  — 通过 Git Bash / bash -lc 执行（Unix 语法）
          - ("shell", None) — 使用 shell=True（Linux/macOS 的 sh，或 Windows 回退 cmd）
    """
    if sys.platform != "win32":
        return ("shell", None)

    candidates: list[Path] = []
    for env_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env_key)
        if not base:
            continue
        if env_key == "LOCALAPPDATA":
            candidates.append(Path(base) / "Programs" / "Git" / "bin" / "bash.exe")
        else:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")

    for path in candidates:
        if path.is_file():
            return ("bash", str(path))

    # which("bash") 可能命中 WSL 的 System32\bash.exe，跳过以避免路径映射问题
    which_bash = shutil.which("bash")
    if which_bash:
        resolved = Path(which_bash).resolve()
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
        try:
            resolved.relative_to(system_root)
            # 位于 SystemRoot 下 → WSL launcher，忽略
        except ValueError:
            return ("bash", str(resolved))

    return ("shell", None)


def _decode_output(data: bytes | None) -> str:
    """解码子进程输出：优先 UTF-8，失败则回退系统首选编码 / GBK。"""
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


def _format_exception(exc: BaseException) -> str:
    """格式化异常，避免 NotImplementedError() 等空消息丢失类型信息。"""
    msg = str(exc).strip()
    if msg:
        return f"{type(exc).__name__}: {msg}"
    return repr(exc)


def _kill_process_tree_sync(pid: int | None) -> None:
    """超时后尽量清理进程树（Windows 用 taskkill /T）。"""
    if not pid:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception:
            pass
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def _subprocess_env() -> dict[str, str]:
    """子进程环境：Windows 下默认 UTF-8，避免 Python print emoji 触发 GBK UnicodeEncodeError。"""
    env = os.environ.copy()
    if sys.platform == "win32":
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
    return env


def _run_command_sync(
    command: str,
    *,
    cwd: str,
    shell_mode: str,
    bash_path: str | None,
) -> str:
    """在工作线程中同步执行命令，避免 Windows SelectorEventLoop 不支持 asyncio subprocess。"""
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": cwd,
        "env": _subprocess_env(),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc: subprocess.Popen[bytes] | None = None
    try:
        if shell_mode == "bash" and bash_path:
            proc = subprocess.Popen([bash_path, "-lc", command], **kwargs)
        else:
            proc = subprocess.Popen(command, shell=True, **kwargs)

        try:
            stdout, stderr = proc.communicate(timeout=_COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_process_tree_sync(proc.pid)
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            return f"命令执行超时 ({_COMMAND_TIMEOUT}s)"
    except Exception as e:
        if proc is not None and proc.poll() is None:
            _kill_process_tree_sync(proc.pid)
        return f"命令执行失败: {_format_exception(e)}"

    result = _decode_output(stdout)
    err_text = _decode_output(stderr)
    if err_text:
        result = f"{result}\n{err_text}" if result else err_text
    return result.strip() or "(no output)"


def _shell_description(mode: str, bash_path: str | None) -> str:
    base = (
        "在项目环境中执行 shell 命令。"
        "用于运行 Python 脚本、下载文件、安装依赖等命令行操作。"
        "命令在项目根目录执行。"
    )
    if mode == "bash":
        return (
            f"{base}"
            f"当前通过 Git Bash 执行（{bash_path}），可使用 cat/ls/grep 等 Unix 命令。"
        )
    if sys.platform == "win32":
        return (
            f"{base}"
            "当前环境未检测到 Git Bash，使用 cmd.exe；"
            "请使用 Windows 命令（如 type/dir/findstr），不要使用 cat/ls/grep。"
        )
    return base


class RunCommandTool(BaseTool):
    """Shell 命令执行工具：允许 Agent 在项目根目录执行命令。风险等级 L2，运行脚本、下载文件等。"""
    name = "run_command"
    risk_level = 2

    def __init__(self):
        self.access_policy: AccessPolicy | None = None
        mode, bash_path = _resolve_shell()
        self._shell_mode = mode
        self._bash_path = bash_path

    @property
    def description(self) -> str:
        return _shell_description(self._shell_mode, self._bash_path)

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 shell 命令",
                    },
                },
                "required": ["command"],
            },
        }

    async def run(self, command: str) -> str:
        # 权限检查
        if self.access_policy:
            error = self.access_policy.check(command)
            if error:
                mode = self.access_policy.describe_mode()
                return f"❌ {error}\n当前Agent权限: {mode}"

        cwd = _project_root or "."
        try:
            return await asyncio.to_thread(
                _run_command_sync,
                command,
                cwd=cwd,
                shell_mode=self._shell_mode,
                bash_path=self._bash_path,
            )
        except Exception as e:
            return f"命令执行失败: {_format_exception(e)}"
