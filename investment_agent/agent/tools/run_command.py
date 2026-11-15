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
from .registry import register_tool

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
          - ("shell", None) — 使用 create_subprocess_shell（Linux/macOS 的 sh，或 Windows 回退 cmd）
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


def _decode_output(data: bytes) -> str:
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


async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """超时后终止进程；Windows 上用 taskkill /T 清理子进程树。"""
    if proc.returncode is not None:
        return
    if sys.platform == "win32" and proc.pid:
        try:
            kill_proc = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await kill_proc.wait()
        except Exception:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
    else:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await proc.communicate()
    except Exception:
        pass


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


@register_tool
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
        proc: asyncio.subprocess.Process | None = None
        try:
            if self._shell_mode == "bash" and self._bash_path:
                # Git Bash：-lc 以 login shell 加载 PATH（含 git 自带的 Unix 工具）
                kwargs: dict = {
                    "stdout": asyncio.subprocess.PIPE,
                    "stderr": asyncio.subprocess.PIPE,
                    "cwd": cwd,
                }
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                proc = await asyncio.create_subprocess_exec(
                    self._bash_path,
                    "-lc",
                    command,
                    **kwargs,
                )
            else:
                kwargs = {
                    "stdout": asyncio.subprocess.PIPE,
                    "stderr": asyncio.subprocess.PIPE,
                    "cwd": cwd,
                }
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                proc = await asyncio.create_subprocess_shell(command, **kwargs)

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_COMMAND_TIMEOUT
            )
            result = _decode_output(stdout)
            if stderr:
                err_text = _decode_output(stderr)
                if err_text:
                    result = f"{result}\n{err_text}" if result else err_text
            return result.strip() or "(no output)"
        except asyncio.TimeoutError:
            if proc is not None:
                await _kill_process_tree(proc)
            return f"命令执行超时 ({_COMMAND_TIMEOUT}s)"
        except Exception as e:
            return f"命令执行失败: {e}"
