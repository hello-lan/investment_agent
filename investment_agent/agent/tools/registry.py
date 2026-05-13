from .base import BaseTool
from .market_data import StockInfoTool, StockPriceTool
# StockRealtimeTool, MarketIndexTool 已注释：依赖 eastmoney.com API，网络不通
from .financials import (
    IncomeStatementTool, BalanceSheetTool, CashFlowTool,
    ValuationTool, FinancialIndicatorTool,
)
from .run_command import RunCommandTool

# 工具注册中心：单例字典存储所有已注册工具
_registry: dict[str, BaseTool] = {}


def _register(tool: BaseTool) -> None:
    _registry[tool.name] = tool


# —— 启动时注册所有内置工具 ——
_register(StockInfoTool())
_register(StockPriceTool())
# 注释原因：这两个工具依赖 eastmoney.com API，当前网络环境下代理无法连通
# _register(StockRealtimeTool())
# _register(MarketIndexTool())
_register(IncomeStatementTool())
_register(BalanceSheetTool())
_register(CashFlowTool())
_register(ValuationTool())
_register(FinancialIndicatorTool())
_register(RunCommandTool())


def get_all_tools() -> list[BaseTool]:
    return list(_registry.values())


def get_tool(name: str) -> BaseTool | None:
    return _registry.get(name)


def get_schemas() -> list[dict]:
    """返回所有工具的 Anthropic tool schema 列表，用于注入 LLM 请求"""
    return [t.schema for t in _registry.values()]
