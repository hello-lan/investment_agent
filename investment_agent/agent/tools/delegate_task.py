"""DelegateTask 工具：将独立子任务委派给子Agent执行。

引擎在 _execute_tool() 中拦截此工具的调用，启动隔离子Agent完成任务。
工具的 run() 方法仅作为 fallback，正常流程不会执行到。
"""

from .base import BaseTool
from .registry import register_tool


@register_tool
class DelegateTaskTool(BaseTool):
    """将独立子任务委派给子Agent在隔离环境中执行。

    子Agent拥有独立的上下文和消息列表，完成后仅将文本结果返回给父Agent。
    可指定子Agent需要使用的技能（skill_names），子Agent会自动加载这些技能的完整说明。
    """

    name = "DelegateTask"
    description = (
        "将独立子任务委派给子Agent执行。子Agent在隔离环境中运行指定的技能，"
        "完成后返回结果。适用于需要多步骤执行的独立任务，如下载财报、PDF转换、"
        "文件切割、专项分析等。支持任意已注册的非编排技能委派，支持嵌套委派（最大深度可配置）。"
        "当编排型(orch)技能的指令中提到'用 xxx 技能...'或'使用 xxx 技能...'时，"
        "调用此工具，将技能名填入 skill_names，将该步骤的具体要求填入 task。"
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
                        "description": (
                            "委派给子Agent的任务描述。应包含具体的执行要求、"
                            "输入参数（如股票代码、文件路径等）和期望的输出。"
                        ),
                    },
                    "skill_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "子Agent需要使用的技能名称列表。子Agent会自动加载"
                            "这些技能的完整说明并注入到其系统提示词中。"
                        ),
                    },
                },
                "required": ["task"],
            },
        }

    async def run(self, task: str, skill_names: list[str] | None = None) -> str:
        """Fallback：正常流程由引擎拦截处理，不会执行到此方法。"""
        return (
            "DelegateTask 需要引擎的拦截机制来执行。"
            "如果看到此消息，说明引擎未正确拦截 DelegateTask 调用。"
        )
