import asyncio

from ...config import PROJECT_ROOT
from .base import BaseTool


class RunCommandTool(BaseTool):
    name = "run_command"
    description = "在项目环境中执行 shell 命令。用于运行 Python 脚本、下载文件、安装依赖等命令行操作。命令在项目根目录执行。"
    risk_level = 2

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
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
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
