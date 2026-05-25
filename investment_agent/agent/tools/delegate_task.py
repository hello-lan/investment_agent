"""DelegateTask 工具：将独立子任务委派给子Agent执行。

引擎在 ToolExecutor 中拦截此工具的调用，启动隔离子Agent（共享预算）完成任务。
工具的 run() 方法仅作为 fallback，正常流程不会执行到。
"""

from .base import BaseTool
from .registry import register_tool


@register_tool
class DelegateTaskTool(BaseTool):
    """将独立子任务委派给子Agent在隔离环境中执行。

    子Agent拥有独立的上下文和消息列表，共享父Agent的 token 预算，
    完成后仅将文本结果返回给父Agent。子Agent为叶子执行器，不可再次委派。
    可指定子Agent需要使用的技能（skill_names），子Agent会自动加载这些技能的完整说明。
    """

    name = "DelegateTask"
    description = (
        "将独立子任务委派给子Agent在隔离环境中执行。子Agent拥有独立的上下文和消息列表，"
        "共享父Agent的 token 预算，完成后仅返回文本执行结果。适用于需要多步骤执行、"
        "工具调用密集的独立子任务，如下载财报、PDF转换、文件切割、专项分析等。"
        "支持任意已注册的非编排技能委派。\n\n"
        "【何时主动委派】分析当前任务结构，满足以下任一条件时应考虑使用本工具：\n"
        "（1）存在多个互不依赖的子任务 — 可逐个委派执行（如分别分析资产负债表、利润表、现金流量表）；\n"
        "（2）子任务步骤多、工具调用密集 — 在隔离上下文中执行可保持父Agent专注全局判断；\n"
        "（3）子任务涉及某个技能的完整执行流程 — 将该技能名填入 skill_names，任务描述填入 task；\n"
        "（4）编排(orch)技能指令要求'用 xxx 技能...'时 — 严格遵循编排指令委派。\n"
        "【约束】不可委派的场景：需要父Agent即时决策的交互式任务、"
        "以及可以单步工具调用完成的简单操作。一次委派只做一件明确的事，避免将多件无关任务打包。"
        "子Agent为叶子执行器，不可再次委派。"
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
