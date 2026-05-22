"""AgentRunConfig — 一次 Agent 运行所需的全部已解析配置。

纯数据 dataclass，不含任何 DB 访问或文件读取。
构建工作由 app/config_factory.py 的 load_agent_run_config() 完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

    # ── Agent 级工具选择（空列表=全部工具，向后兼容）──
    tools: list[str] = field(default_factory=list)

    # ── 工具裁剪参数 ──
    tool_trim_limits: dict = field(default_factory=dict)

    # ── 上下文参数 ──
    context: dict = field(default_factory=dict)

    # ── Provider 定价信息 ──
    input_price: float | None = None
    output_price: float | None = None
    currency: str = "USD"
