from __future__ import annotations

import asyncio

from .access_policy import AccessPolicy
from .base import BaseTool
from .registry import register_tool

# 项目根目录，由 app 层在启动时注入
_project_root: str | None = None


def set_project_root(path: str) -> None:
    global _project_root
    _project_root = path


@register_tool
class RunCommandTool(BaseTool):
    """Shell 命令执行工具：允许 Agent 在项目根目录执行命令。风险等级 L2，运行脚本、下载文件等。"""
    name = "run_command"
    description = "在项目环境中执行 shell 命令。用于运行 Python 脚本、下载文件、安装依赖等命令行操作。命令在项目根目录执行。"
    risk_level = 2

    def __init__(self):
        self.access_policy: AccessPolicy | None = None

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

        try:
            # 异步子进程，120 秒超时，在项目根目录执行
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=_project_root or ".",
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=120
            )
            result = stdout.decode("utf-8", errors="replace")
            if stderr:
                result += "\n" + stderr.decode("utf-8", errors="replace")
            return result.strip() or "(no output)"
        except asyncio.TimeoutError:
            proc.kill()
            return "命令执行超时 (120s)"
        except Exception as e:
            return f"命令执行失败: {e}"
