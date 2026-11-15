"""已废弃：通用 Subagent 工具。

请改用用户定义 Subagent（Agent 页「Subagent 定义」+ 主 Agent 挂载）。
保留此模块仅避免旧 import 报错。
"""

from .base import BaseTool


class SubagentTool(BaseTool):
    """已废弃，不再注册到工具目录。"""

    name = "Subagent"
    description = "已废弃：请使用用户定义 Subagent。"
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                },
                "required": ["task"],
            },
        }

    async def run(self, **kwargs) -> str:
        raise NotImplementedError(
            "内置 Subagent 工具已废弃，请在 Agent 页创建并挂载用户定义 Subagent。"
        )
