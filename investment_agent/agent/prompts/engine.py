"""引擎内部元提示：慢思考、截断续写、日期与步数预算。"""

from __future__ import annotations

import re

SLOW_THINK_PROMPT = (
    "[慢思考 @ step {step}] 请简要评估：\n"
    "1. 当前进度是否符合目标？\n"
    "2. 策略是否需要调整？\n"
    "3. 是否存在风险或偏离？\n"
    "请用1-3句话回答，不要调用工具。\n"
    "禁止在反思中输出任何工具调用格式（如 <invoke>、<parameter> 等标签），"
    "只做策略评估，不要建议具体命令或操作。"
)

TRUNCATION_CONTINUE_PROMPT = "你的上一次回复因达到token上限被截断，请继续完成未完成的部分。"


def slow_think_reflection(step: int, reflection: str) -> str:
    """慢思考结果写回对话时的用户消息。"""
    return f"[慢思考反思 @ step {step}] {reflection}"

DATE_NOTE = (
    "[系统信息] 当前时间为 {year} 年 {month} 月 {day} 日 "
    "{hour:02d}:{minute:02d}。"
    "请以当前时间为基准判断时间相关的问题。\n\n"
)

DATE_NOTE_RE = re.compile(
    r"^\[系统信息\] 当前时间为 .+?请以当前时间为基准判断时间相关的问题。\n\n",
    re.DOTALL,
)

PROGRESS_EVAL = "请基于对话历史评估当前任务进展是否正常。"

STEP_BUDGET_MARKER = "步数预算警告"

STEP_BUDGET_WARNING = (
    "[步数预算警告] 剩余步数: {remaining}/{max_steps}。"
    "请评估当前进度：如果仍在数据准备阶段，考虑跳过中间步骤，"
    "直接使用已有数据快速进入核心分析。优先委派而非亲自调试。"
)
