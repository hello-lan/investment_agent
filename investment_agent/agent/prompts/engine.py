"""引擎内部元提示：规划、慢思考、截断续写、日期与步数预算。"""

from __future__ import annotations

import re

TASK_PLANNER_SYSTEM = "你是一个任务规划助手，负责为子Agent生成精确的任务指令。"

TASK_PLANNER_PROMPT = (
    "你是一个任务规划者。请基于以下对话上下文，为子Agent生成一条完整的任务指令。\n\n"
    "项目根目录: {project_root}\n\n"
    "父Agent要求: {task}\n"
    "{skill_info}\n\n"
    "要求：\n"
    "1. 从对话上下文中提取子Agent执行所需的关键信息（股票代码、文件路径、年份、输入输出目录等）\n"
    "2. **所有路径使用相对项目根的相对路径**（正斜杠，如 data/reports/...）；Windows/Linux 均禁止再 `cd`；Windows 上禁止 `/d/...`、`D:\\\\...` 盘符路径\n"
    "3. 明确说明操作步骤和期望输出格式\n"
    "4. 确保指令完整自包含——子Agent仅凭此指令即可执行，无需额外询问\n"
    "5. 如果指定了技能，必须在指令开头明确要求：\"首先按技能说明用 run_python_script 执行脚本（必要时再 Skill 加载说明）；仅当专用工具无法覆盖时用 run_command\"\n"
    "6. **范围约束**：在指令末尾明确声明处理范围（股票代码 + 文件列表），并注明'只处理上述文件，禁止查找或处理其他股票的文件'\n"
    "7. 用中文输出，不要添加解释性文字，直接输出任务指令"
)

SUBAGENT_TASK_PLANNER_SYSTEM = "你是一个文件型子任务规划助手，负责生成安全、聚焦的子Agent任务说明。"

SUBAGENT_TASK_PLANNER_PROMPT = (
    "你是一个任务规划者。请基于以下对话上下文，为文件子Agent生成一条完整的任务指令。\n\n"
    "项目根目录: {project_root}\n"
    "允许读取的 targets: {targets}\n"
    "期望输出: {expected_output}\n"
    "授权输出路径: {output_path}\n\n"
    "父Agent要求: {task}\n\n"
    "要求：\n"
    "1. 只围绕已授权的 targets 展开，不要扩展到其他文件或目录\n"
    "2. 如需写文件，只能写入 {project_root}/data 目录及其子目录；若仅提供文件名，默认写入 {project_root}/data/tmp\n"
    "3. 指令中明确要读取哪些文件、筛选什么信息、输出什么结果\n"
    "4. 指令必须自包含，禁止让子Agent自行猜测路径或范围\n"
    "5. 用中文输出，不要添加解释性文字，直接输出任务指令"
)

SLOW_THINK_PROMPT = (
    "[慢思考 @ step {step}] 请简要评估：\n"
    "1. 当前进度是否符合目标？\n"
    "2. 策略是否需要调整？\n"
    "3. 是否存在风险或偏离？\n"
    "请用1-3句话回答，不要调用工具。\n"
    "禁止在反思中输出任何工具调用格式（如 <invoke>、<parameter>、DelegateTask 等标签），"
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
