"""Agent 配置：运行数据结构和默认值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import OffloadSummaryStrategy, RuntimeTrimStrategy


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
- 项目根目录: {PROJECT_ROOT}
- 技能脚本路径: {PROJECT_ROOT}/extensions/skills/<skill_name>/scripts/
  - 运行脚本时使用绝对路径，不要 `cd` 后再执行
- 数据目录: {PROJECT_ROOT}/data/reports/<股票代码>/
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


@dataclass
class EngineConfig:
    """引擎执行参数子集，供 AgentEngine 构造使用。"""

    max_steps: int = 60
    slow_think_interval: int = 3
    token_budget: int = 100_000
    loop_detection_threshold: int = 3
    context_trim_interval: int = 0
    tool_trim_limits: dict = field(default_factory=dict)
    max_subagent_depth: int = 3
    offload_threshold: int = 800
    offload_summary_strategy: str = OffloadSummaryStrategy.TRUNCATE
    offload_summary_chars: int = 200


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
    token_budget: int = 100000
    loop_detection_threshold: int = 3
    context_trim_interval: int = 0
    runtime_trim_strategy: str = RuntimeTrimStrategy.COMPRESS

    # ── 上下文卸载参数 ──
    offload_threshold: int = 800
    offload_summary_strategy: str = OffloadSummaryStrategy.TRUNCATE
    offload_summary_chars: int = 200
    offload_summary_model_id: str | None = None

    # ── Agent 级工具选择（空列表=全部工具，向后兼容）──
    tools: list[str] = field(default_factory=list)

    # ── Agent 级技能选择（空列表=不启用任何技能）──
    skills: list[str] = field(default_factory=list)

    # ── 工具裁剪参数 ──
    tool_trim_limits: dict = field(default_factory=dict)

    # ── 上下文参数 ──
    context: dict = field(default_factory=dict)

    # ── 子Agent配置 ──
    max_subagent_depth: int = 3

    # ── Provider 定价信息 ──
    input_price: float | None = None
    output_price: float | None = None
    currency: str = "USD"

    # ── 压缩模型（独立的廉价 Provider，用于上下文摘要）──
    compression_provider: Any = None

    # ── 卸载摘要模型（独立的廉价 Provider，用于 tool_result 摘要）──
    offload_summary_provider: Any = None
