"""Agent 包的所有抽象接口（Protocol）。

依赖方向：agent 只定义接口，app 层提供实现，agent 绝不 import app。
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Protocol


class ExecutionLoop(Protocol):
    """LLM 执行策略接口。

    当前实现：agent/core/engine.py 的 AgentEngine（双循环模式）。
    可替换为 Tree-of-Thought、ReAct 等其他执行策略。

    system_prompt / tools / provider 等在构造时注入，
    run() 仅接收消息列表并逐事件 yield 字典。
    """

    @property
    def total_input_tokens(self) -> int: ...

    @property
    def total_output_tokens(self) -> int: ...

    @property
    def total_cache_read_tokens(self) -> int: ...

    @property
    def total_cache_creation_tokens(self) -> int: ...

    async def run(
        self,
        messages: list[dict],
    ) -> AsyncGenerator[dict, None]:
        """执行 LLM 循环，逐事件 yield 字典。"""
        ...


class ContextManagerProtocol(Protocol):
    """上下文管理策略接口。

    当前实现：agent/context/manager.py 的 ContextManager（Head-Body-Tail 模式）。
    可替换为滑动窗口、分层摘要等策略。
    """

    async def prepare(
        self,
        system_prompt: str,
        tools: list[dict],
        messages: list[dict],
    ) -> Any:
        """处理上下文预算，返回 ContextResult。

        返回对象需包含以下属性：
        - system_prompt: str | list[dict]
        - tools: list[dict]
        - messages: list[dict]
        - system_tokens: int
        - tools_tokens: int
        - messages_tokens: int
        - total_tokens: int
        - model_max_tokens: int
        - warnings: list[str]
        """
        ...


class Storage(Protocol):
    """持久化接口。

    agent 通过此协议读写数据，不直接依赖 app.db。
    当前实现：app/storage.py 的 SqliteStorage。
    """

    async def create_or_get_session(
        self, session_id: str, agent_id: str | None, title: str,
    ) -> str:
        """创建或复用会话，返回 session_id。"""
        ...

    async def save_user_message(
        self, session_id: str, content: str,
    ) -> str:
        """保存用户消息，返回 message_id。"""
        ...

    async def save_assistant_message(
        self, session_id: str, content: str,
    ) -> str:
        """保存 assistant 回复，返回 message_id。"""
        ...

    async def load_messages(self, session_id: str) -> list[dict]:
        """加载会话的所有历史消息（user + assistant）。"""
        ...

    async def get_agent_config(self, agent_id: str) -> dict | None:
        """查询 agent 配置（system_prompt, model_id, skills 等）。"""
        ...

    async def get_model_config(self, model_id: str | None = None) -> dict | None:
        """查询模型配置（api_key, model, base_url 等）。默认模型时 model_id 为 None。"""
        ...

    async def get_session_agent_id(self, session_id: str) -> str | None:
        """查询会话绑定的 agent_id。"""
        ...


class LifecycleHooks(Protocol):
    """可观测性回调接口。

    当前实现：app/observability/hooks_impl.py 的 ObservabilityHooks。
    """

    async def on_event(
        self, step: int | None, event_type: str,
        detail: dict[str, Any] | None,
    ) -> None:
        """每个执行事件（tool_call, tool_result, error, slow_think）触发。"""
        ...

    async def on_cost(
        self, model: str, input_tokens: int, output_tokens: int,
        input_price: float | None = None,
        output_price: float | None = None,
        currency: str = "USD",
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        """终端事件（done/error/interrupted）时触发，记录 Token 成本和缓存指标。"""
        ...

    async def on_context_budget(self, context_result: Any) -> None:
        """上下文准备完成后触发，记录预算信息。"""
        ...

    async def on_cache_metrics(
        self, step: int | None,
        cache_read_tokens: int, cache_creation_tokens: int,
    ) -> None:
        """缓存命中/创建时触发。"""
        ...
