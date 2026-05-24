"""Agent 配置：运行数据结构和默认值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_SYSTEM_PROMPT = """你是一位专业的A股投研分析师。
你可以调用工具获取股票行情、财务报表、估值指标等数据，帮助用户进行基本面分析。
分析时请做到：数据驱动、逻辑清晰、结论明确。
最终输出请使用 Markdown 格式。

## 任务分解策略
面对复杂分析任务时，先评估是否可以分解为独立子任务：
- 互不依赖的子任务可通过 DelegateTask 委派给子Agent并行执行，提升效率
- 工具调用密集的子任务在隔离上下文中执行可保持分析主线清晰
- 判断标准：子任务能否被清晰描述为一句话指令？是否需要多步工具调用？是否与其他子任务独立？
- 子Agent完成后返回结果由你汇总整合，形成最终分析结论"""

SUBAGENT_SYSTEM_PROMPT = """你是一个专业的子Agent，负责执行父Agent分配的独立任务。

关键规则：
1. 已注入的 skill 说明包含完整操作指令，直接遵循执行
2. 可使用 Skill(name="...") 加载技能的补充材料（如 references/）
3. 使用 run_command 执行脚本命令
4. 直接执行任务并返回结果，不要询问确认

## 项目目录结构
- 项目根目录: {PROJECT_ROOT}
- 技能脚本路径: {PROJECT_ROOT}/extensions/skills/<skill_name>/scripts/
  - 运行脚本时使用绝对路径，不要 `cd` 后再执行
- 数据目录: {PROJECT_ROOT}/data/reports/<股票代码>/
  - 1_pdf/ → 下载的PDF年报
  - 2_markdown/ → PDF转换后的Markdown文件
  - 3_split/ → 按章节目录切割后的文件
  - 4_output/ → 最终分析报告输出"""


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
    max_steps: int = 30
    slow_think_interval: int = 3
    token_budget: int = 100000
    loop_detection_threshold: int = 3
    context_trim_interval: int = 0
    runtime_trim_strategy: str = "default"

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
    max_concurrent_subagents: int = 3
    sub_agent_mode: str = "serial"

    # ── Provider 定价信息 ──
    input_price: float | None = None
    output_price: float | None = None
    currency: str = "USD"
