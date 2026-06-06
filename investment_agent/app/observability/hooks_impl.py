"""ObservabilityHooks — 实现 LifecycleHooks 协议。

将 agent 包的事件回调桥接到 app 层的 log_trace / log_cost。
"""

from __future__ import annotations

from typing import Any

from .cost_tracker import log_cost
from .trace import log_trace


class ObservabilityHooks:
    """可观测性回调实现：将 agent 生命周期事件写入 trace_log / cost_log。

    session_id 和 agent_name 可在构造后设置（AgentRunner.run() 会填充它们）。
    """

    def __init__(
        self,
        task_id: str,
        session_id: str = "",
        agent_name: str | None = None,
    ):
        self.task_id = task_id
        self.session_id = session_id
        self.agent_name = agent_name

    async def on_event(
        self, step: int | None, event_type: str,
        detail: dict[str, Any] | None,
    ) -> None:
        await log_trace(
            self.session_id, self.task_id, step, event_type, detail,
            agent_name=self.agent_name,
        )

    async def on_cost(
        self, model: str, input_tokens: int, output_tokens: int,
        input_price: float | None = None,
        output_price: float | None = None,
        currency: str = "USD",
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        await log_cost(
            session_id=self.session_id,
            task_id=self.task_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            agent_name=self.agent_name,
            input_price=input_price,
            output_price=output_price,
            currency=currency,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )

    async def on_context_budget(self, context_result: Any) -> None:
        detail = {
            "system_prompt": context_result.system_prompt,
            "tools": context_result.tools,
            "system_tokens": context_result.system_tokens,
            "tools_tokens": context_result.tools_tokens,
            "messages_tokens": context_result.messages_tokens,
            "total_tokens": context_result.total_tokens,
            "model_max": context_result.model_max_tokens,
            "warnings": context_result.warnings,
        }

        await log_trace(
            self.session_id, self.task_id, None, "context_budget",
            detail,
            agent_name=self.agent_name,
        )

    async def on_cache_metrics(
        self, step: int | None,
        cache_read_tokens: int, cache_creation_tokens: int,
    ) -> None:
        await log_trace(
            self.session_id, self.task_id, step, "cache_metrics",
            {
                "cache_read_tokens": cache_read_tokens,
                "cache_creation_tokens": cache_creation_tokens,
            },
            agent_name=self.agent_name,
        )
