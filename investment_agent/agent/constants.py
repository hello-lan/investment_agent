"""Agent 层共享枚举类型 — 消除魔法字符串。

引入 StrEnum 类型定义，替换散布在各模块中的字符串字面量，
提升类型安全性和 IDE 支持。
"""

from enum import StrEnum


# ── 技能类型 ──────────────────────────────────────────────────────────

class SkillType(StrEnum):
    """技能类型：原子技能 vs 编排技能。"""
    ATOMIC = "atomic"
    ORCH = "orch"


# ── Provider 类型 ─────────────────────────────────────────────────────

class ProviderType(StrEnum):
    """LLM Provider 类型标识。"""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


# ── LLM 停止原因 ──────────────────────────────────────────────────────

class StopReason(StrEnum):
    """LLM 响应停止原因，统一 Anthropic 和 OpenAI 的表示。"""
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    LENGTH = "length"


# ── 运行时上下文裁剪策略 ──────────────────────────────────────────────

class RuntimeTrimStrategy(StrEnum):
    """运行时上下文压缩策略。"""
    COMPRESS = "compress"
    OFF = "off"


# ── 上下文卸载摘要策略 ────────────────────────────────────────────────

class OffloadSummaryStrategy(StrEnum):
    """tool_result 卸载时的摘要生成策略。"""
    TRUNCATE = "truncate"
    LOCAL = "local"
    LLM = "llm"


# ── 消息角色 ──────────────────────────────────────────────────────────

class MessageRole(StrEnum):
    """对话消息角色。"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


# ── Agent 事件类型 ─────────────────────────────────────────────────────

class EventType(StrEnum):
    """Agent 引擎产出的事件类型（SSE stream 中的 type 字段值）。"""
    # 生命周期
    DONE = "done"
    ERROR = "error"
    INTERRUPTED = "interrupted"
    STEP_START = "step_start"

    # 文本
    TEXT_DELTA = "text_delta"

    # LLM
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"

    # 工具
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # 慢思考
    SLOW_THINK = "slow_think"

    # 上下文
    CONTEXT_TRIM = "context_trim"
    CONTEXT_BUDGET = "context_budget"
    BUDGET_STATUS = "budget_status"

    # 子Agent 内部事件（不直接暴露给前端）
    _DELEGATE_DONE = "__delegate_done__"
    _DELEGATE_ERROR = "__delegate_error__"
