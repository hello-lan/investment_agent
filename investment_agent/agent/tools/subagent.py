"""Subagent 工具：为 react_subagent loop 发起安全文件子任务。"""

from .base import BaseTool
from .registry import register_tool


@register_tool
class SubagentTool(BaseTool):
    """发起一个受限文件作用域的通用子Agent。"""

    name = "Subagent"
    description = (
        "将文件型、搜索型、筛选型或写作型子任务交给安全子Agent执行。"
        "子Agent只拥有低风险的 Python 文件工具（列举、读取、搜索、写入授权输出），"
        "不会使用 shell 命令。适用于需要在一组文件中做局部读取、检索、过滤、摘录、"
        "或生成中间摘要文件的场景。调用时必须给出清晰的 task 和明确的 targets 范围。"
    )
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "子Agent要完成的聚焦任务说明。",
                    },
                    "targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "子Agent允许读取的文件或目录路径列表。",
                    },
                    "expected_output": {
                        "type": "string",
                        "description": "期望返回的结果形式，例如摘要、表格、要点列表等。",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "若需要指定落盘位置，可提供 data/ 目录下的输出文件路径。",
                    },
                },
                "required": ["task", "targets"],
            },
        }

    async def run(
        self,
        task: str,
        targets: list[str],
        expected_output: str | None = None,
        output_path: str | None = None,
    ) -> str:
        raise NotImplementedError(
            "Subagent 由 ToolExecutor 拦截执行，不应直接调用 run()。"
        )
