"""工具两阶段模型：装饰器注册 → 引擎激活。

- Phase 1 — 类上用 @register_tool 装饰器，实例自动存入 _tool_registry
- Phase 2 — runner 根据 agent 配置的 tools 列表，调用 engine.register_tool()

_tool_registry 只是一个查询目录，加入 _tool_registry 不等于工具生效。
"""

from __future__ import annotations

from .base import BaseTool

# 工具编目：工具名 → 工具实例（类定义时由 @register_tool 自动填入）
_tool_registry: dict[str, BaseTool] = {}

# 始终自动绑定的基础设施工具（Skill 加载 + 命令执行）
AUTO_BOUND_TOOLS: set[str] = {"Skill", "run_command"}


def register_tool(cls):
    """装饰器：将工具实例自动编目。类定义时即生效，无需手动调用。"""
    instance = cls()
    _tool_registry[instance.name] = instance
    return cls


# —— 导入工具模块，触发 @register_tool 装饰器 ——
# 这些 import 的唯一目的是让工具类的 @register_tool 生效。
# 不再需要手动逐个 _register() 调用。
from .market_data import StockInfoTool, StockPriceTool  # noqa: F401
# StockRealtimeTool, MarketIndexTool 已注释：依赖 eastmoney.com API，网络不通
from .financials import (  # noqa: F401
    IncomeStatementTool, BalanceSheetTool, CashFlowTool,
    ValuationTool, FinancialIndicatorTool,
)
from .run_command import RunCommandTool  # noqa: F401
from .delegate_task import DelegateTaskTool  # noqa: F401
from ..skills.tool import SkillTool  # noqa: F401


# ── 查询 API（_tool_registry 是内部实现，外部只通过以下函数访问）──

def get_all_tool_infos() -> list[dict]:
    """返回所有已编目工具的元信息（供前端展示）"""
    return [
        {
            "name": t.name,
            "description": t.description,
            "auto_bound": t.name in AUTO_BOUND_TOOLS,
        }
        for t in _tool_registry.values()
    ]


def get_tool(name: str) -> BaseTool | None:
    return _tool_registry.get(name)


def get_schemas_for_names(names: set[str]) -> list[dict]:
    """只返回指定名称的工具 Anthropic tool schema"""
    return [t.schema for t in _tool_registry.values() if t.name in names]
