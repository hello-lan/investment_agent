"""Agent 配置：运行数据结构和默认值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import OffloadSummaryStrategy, LoopMode

# ── 默认值常量（全局单一来源，避免多文件硬编码）──────────────────────────
PLANNING_MAX_TOKENS_DEFAULT = 1024  # 委派任务指令生成的单轮输出上限默认值
SUBAGENT_WORKSPACE_DIR_DEFAULT = "data/tmp/subagents"
MAX_PARALLEL_SUBAGENTS_DEFAULT = 3


@dataclass
class EngineConfig:
    """引擎执行参数子集，供 AgentEngine 构造使用。"""

    max_steps: int = 60
    slow_think_interval: int = 3
    loop_mode: str = LoopMode.DUAL_LOOP
    token_budget: int = 100_000
    subagent_token_budget: int = 100_000  # 每次委派的独立额度，不占用父预算（兼容旧扁平键）
    subagent: dict = field(default_factory=dict)  # 子运行时默认块（L1）
    loop_detection_threshold: int = 3
    runtime_context_compression_enabled: bool = True
    context_trim_token_threshold: int = 0  # input_tokens 超过此阈值时触发安全压缩（0=禁用）
    max_subagent_depth: int = 3
    max_parallel_subagents: int = MAX_PARALLEL_SUBAGENTS_DEFAULT
    offload_threshold: int = 800
    offload_summary_strategy: str = OffloadSummaryStrategy.TRUNCATE
    offload_summary_chars: int = 200
    planning_max_tokens: int = PLANNING_MAX_TOKENS_DEFAULT  # 任务指令生成单轮输出上限
    subagent_workspace_dir: str = SUBAGENT_WORKSPACE_DIR_DEFAULT


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
    max_single_turn_output_tokens: int | None = None  # 单轮 LLM 回复的最大输出 token；传给 API 的 max_tokens

    # ── 引擎参数 ──
    max_steps: int = 60
    slow_think_interval: int = 3
    loop_mode: str = LoopMode.DUAL_LOOP
    token_budget: int = 100000
    subagent_token_budget: int = 100000  # 每次委派的独立额度，不占用父预算（兼容旧扁平键）
    subagent: dict = field(default_factory=dict)  # 子运行时默认块（L1）
    loop_detection_threshold: int = 3
    runtime_context_compression_enabled: bool = True
    context_trim_token_threshold: int = 0
    planning_max_tokens: int = PLANNING_MAX_TOKENS_DEFAULT  # 任务指令生成单轮输出上限

    # ── 上下文卸载参数 ──
    offload_threshold: int = 800
    offload_summary_strategy: str = OffloadSummaryStrategy.TRUNCATE
    offload_summary_chars: int = 200

    # ── Agent 级工具选择（保存的就是完整勾选结果）──
    tools: list[str] = field(default_factory=list)

    # ── Agent 级技能选择（空列表=不启用任何技能）──
    skills: list[str] = field(default_factory=list)

    # ── 挂载的用户定义 Subagent 快照 ──
    mounted_subagents: list[dict] = field(default_factory=list)

    # ── 上下文参数 ──
    context: dict = field(default_factory=dict)

    # ── 子Agent配置 ──
    max_subagent_depth: int = 3
    max_parallel_subagents: int = MAX_PARALLEL_SUBAGENTS_DEFAULT
    subagent_workspace_dir: str = SUBAGENT_WORKSPACE_DIR_DEFAULT

    # ── Provider 定价信息 ──
    input_price: float | None = None
    output_price: float | None = None
    currency: str = "USD"
