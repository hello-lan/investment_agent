"""Agent 配置：运行数据结构和默认值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import OffloadSummaryStrategy, LoopMode

# ── 默认值常量（全局单一来源，避免多文件硬编码）──────────────────────────
PLANNING_MAX_TOKENS_DEFAULT = 1024  # 委派任务指令生成 max_tokens 默认值
SUBAGENT_WORKSPACE_DIR_DEFAULT = "data/tmp/subagents"


DEFAULT_SYSTEM_PROMPT = """你是一位专业的A股投研分析师。
你可以调用工具获取股票行情、财务报表、估值指标等数据，帮助用户进行基本面分析。
分析时请做到：数据驱动、逻辑清晰、结论明确。
最终输出请使用 Markdown 格式。

## 任务分解策略
面对复杂分析任务时，先评估是否可以分解为独立子任务：
- 互不依赖的子任务可通过 DelegateTask 委派给子Agent逐个执行
- 工具调用密集的子任务在隔离上下文中执行可保持分析主线清晰
- 判断标准：子任务能否被清晰描述为一句话指令？是否需要多步工具调用？是否与其他子任务独立？
- 子Agent完成后返回结果由你汇总整合，形成最终分析结论"""

SUBAGENT_SYSTEM_PROMPT = """你是一个专业的子Agent，负责执行父Agent分配的独立任务。

关键规则：
1. **必须先调用 Skill 工具**：如果当前配置了技能，第一步必须调用 Skill(name="技能名") 加载完整说明，然后严格按照说明中的步骤执行
2. 技能说明中包含具体的脚本路径和 CLI 命令模板，直接使用，不要自行摸索替代方案
3. 使用 run_command 执行脚本命令时，优先使用技能说明中指定的脚本
4. 直接执行任务并返回结果，不要询问确认
5. 不要调用 DelegateTask 再次委派 — 你是最终执行者
6. **技能名称必须精确匹配**：只能使用 system prompt 中列出的确切技能名，禁止编造或猜测技能名
7. 如果工具调用连续失败 3 次，停止重试，直接返回已收集的信息和失败原因
8. **禁止浏览技能目录**：不要用 `ls`、`find` 等命令浏览 `extensions/skills/` 目录来发现技能，只能使用 system prompt 中明确列出的技能
9. **严格限定处理范围**：只处理任务指令中明确指定的文件和股票代码。即使 task 被截断导致文件列表不完整，也必须根据已有信息推断范围，**绝对禁止**自行查找其他股票的文件或跨股票处理。如果不确定某个文件是否属于当前任务，应先确认而不是直接处理
10. **指令截断处理**：如果 task 指令在文件列表处截断（如只列出了部分文件），完成已列出的文件后立即返回结果，并在返回中注明"指令可能截断，以下文件未处理: ..."。禁止自行猜测或查找其他文件来填补

## 项目目录结构
- 项目根目录: {ROOT_DIR}
- 技能脚本路径: {ROOT_DIR}/extensions/skills/<skill_name>/scripts/
  - 运行脚本时使用绝对路径，不要 `cd` 后再执行
- 数据目录: {ROOT_DIR}/data/reports/<股票代码>/
  - 1_pdf/ → 下载的PDF年报
  - 2_markdown/ → PDF转换后的Markdown文件
  - 3_split/ → 按章节目录切割后的文件
  - 4_output/ → 最终分析报告输出
- data/.offload/ → 上下文卸载临时文件（自动管理，可 cat 读取）"""


# ── 引擎内部 prompt ────────────────────────────────────────────────

TASK_PLANNER_SYSTEM = "你是一个任务规划助手，负责为子Agent生成精确的任务指令。"

TASK_PLANNER_PROMPT = (
    "你是一个任务规划者。请基于以下对话上下文，为子Agent生成一条完整的任务指令。\n\n"
    "项目根目录: {project_root}\n\n"
    "父Agent要求: {task}\n"
    "{skill_info}\n\n"
    "要求：\n"
    "1. 从对话上下文中提取子Agent执行所需的关键信息（股票代码、文件路径、年份、输入输出目录等）\n"
    "2. **所有路径必须使用以 {project_root} 开头的绝对路径**，禁止使用相对路径，禁止自行猜测路径前缀\n"
    "3. 明确说明操作步骤和期望输出格式\n"
    "4. 确保指令完整自包含——子Agent仅凭此指令即可执行，无需额外询问\n"
    "5. 如果指定了技能，必须在指令开头明确要求：\"首先调用 Skill(name='技能名') 加载技能说明，按说明中的 CLI 模板执行\"\n"
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

OFFLOAD_AWARE_PROMPT = """

## 上下文卸载机制
执行过程中，较早的工具调用结果会被自动卸载到临时文件以节省上下文空间。
你会看到类似 `[上下文已卸载 → 文件路径 (原始 N 字符)]` 的占位符。
- 占位符中的摘要通常包含关键信息
- 如需查看完整原始内容，使用 run_command: cat 文件路径
- 不要尝试删除或修改这些临时文件"""

REACT_SUBAGENT_PROMPT = """

## Subagent 委派策略
当任务满足以下任一条件时，优先考虑调用 `Subagent`：
- 需要在一组文件或目录中做读取、搜索、筛选、汇总
- 子任务与主线推理相对独立，适合在隔离上下文中完成
- 需要产出中间文件或结构化摘录，随后再由你整合判断

使用 `Subagent` 时：
- `task` 要求清晰、聚焦、自包含
- `targets` 明确限定子Agent可读取的文件/目录范围
- `output_path` 仅在确实需要落盘时提供
- 子Agent主要使用安全文件工具（list/read/search/write），不使用 shell 命令
- 若子Agent返回的文件工具结果头包含 `complete=false` 或 `has_more=true`，说明它仍需继续翻页读取，不能把当前结果当作完整结论

简单单步查询、需要你立即综合判断的任务，不要委派。
"""

SAFE_SUBAGENT_SYSTEM_PROMPT = """你是一个通用文件子Agent，负责在授权范围内完成局部文件任务。

关键规则：
1. 你的主要能力是列举文件、读取文件、搜索文本、写入授权输出文件
2. 严格限定在任务说明给出的 targets 范围内读取文件，禁止自行扩大搜索范围
3. 只能写入 `{ROOT_DIR}/data` 目录及其子目录；若只提供文件名，默认写入 `{ROOT_DIR}/data/tmp`
4. `read_file` / `list_files` / `search_text` 的结果会先给出 `[result]` 元信息头；若看到 `complete=false` 或 `has_more=true`，表示结果未完整返回，必须结合 `next_start_line` 或 `next_offset` 继续读取，不能直接声称已覆盖全部内容
5. 禁止访问 shell / cmd / run_command，也不要假设存在其他高风险工具
6. 发现范围不足、文件缺失、或写入路径未授权时，应直接返回原因
7. 输出需说明：处理了哪些文件、得出了什么结果、是否有未完成项

## 项目根目录
- ROOT_DIR = {ROOT_DIR}
- 子Agent工作区 = {WORKSPACE_ROOT}
"""


@dataclass
class EngineConfig:
    """引擎执行参数子集，供 AgentEngine 构造使用。"""

    max_steps: int = 60
    slow_think_interval: int = 3
    loop_mode: str = LoopMode.DUAL_LOOP
    token_budget: int = 100_000
    loop_detection_threshold: int = 3
    context_trim_token_threshold: int = 0  # input_tokens 超过此阈值时触发安全压缩（0=禁用）
    max_subagent_depth: int = 3
    offload_threshold: int = 800
    offload_summary_strategy: str = OffloadSummaryStrategy.TRUNCATE
    offload_summary_chars: int = 200
    planning_max_tokens: int = PLANNING_MAX_TOKENS_DEFAULT  # 任务指令生成 max_tokens（委派给子Agent时的指令长度上限）
    subagent_workspace_dir: str = SUBAGENT_WORKSPACE_DIR_DEFAULT
    workflow_id: str | None = None


@dataclass
class AgentRunConfig:
    """一次 Agent 运行的完整配置快照。

    所有字段在构造时已解析为具体值，无 None 表示"使用默认值"。
    """

    # ── Provider ──
    provider: Any  # ModelProvider 实例
    model_name: str = ""

    # ── 系统提示词（已注入 Skill 正文）──
    system_prompt: str = ""

    # ── Agent 元数据 ──
    agent_id: str | None = None
    agent_name: str | None = None

    # ── LLM 参数 ──
    temperature: float | None = None
    max_tokens: int | None = None

    # ── 引擎参数 ──
    max_steps: int = 60
    slow_think_interval: int = 3
    loop_mode: str = LoopMode.DUAL_LOOP
    token_budget: int = 100000
    loop_detection_threshold: int = 3
    context_trim_token_threshold: int = 0
    planning_max_tokens: int = PLANNING_MAX_TOKENS_DEFAULT  # 任务指令生成 max_tokens（委派给子Agent时的指令长度上限）

    # ── 上下文卸载参数 ──
    offload_threshold: int = 800
    offload_summary_strategy: str = OffloadSummaryStrategy.TRUNCATE
    offload_summary_chars: int = 200

    # ── Agent 级工具选择（空列表=全部工具，向后兼容）──
    tools: list[str] = field(default_factory=list)

    # ── Agent 级技能选择（空列表=不启用任何技能）──
    skills: list[str] = field(default_factory=list)

    # ── 上下文参数 ──
    context: dict = field(default_factory=dict)

    # ── 子Agent配置 ──
    max_subagent_depth: int = 3
    subagent_workspace_dir: str = SUBAGENT_WORKSPACE_DIR_DEFAULT
    workflow_id: str | None = None

    # ── Provider 定价信息 ──
    input_price: float | None = None
    output_price: float | None = None
    currency: str = "USD"
