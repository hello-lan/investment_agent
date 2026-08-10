"""Plan Execute 执行引擎：先规划，再委派执行，最后汇总。"""

from .base_loop import BaseLoopEngine


_PLAN_EXECUTE_GUIDANCE = (
    "\n\n## 规划执行模式要求\n"
    "你当前运行在 plan_execute 模式。处理复杂任务时，优先遵循以下阶段：\n"
    "1. 先识别目标，并将任务拆分为 2-5 个可独立推进的阶段；\n"
    "2. 能明确限定文件范围的阶段，优先使用 Subagent；\n"
    "3. 需要技能、脚本或多步工具链的阶段，优先使用 DelegateTask；\n"
    "4. 每次委派只处理一个聚焦子问题，收到结果后再进入下一阶段；\n"
    "5. 所有阶段完成后，由你统一交叉验证并输出最终结论。\n"
    "若任务本身很简单，也可以直接完成，不必强行委派。"
)


class PlanExecuteLoopEngine(BaseLoopEngine):
    """带显式规划与委派倾向的执行引擎。"""

    def prepare_run(self, messages: list[dict]) -> list[dict]:
        messages = super().prepare_run(messages)
        messages.append({
            "role": "user",
            "content": _PLAN_EXECUTE_GUIDANCE,
        })
        return messages
