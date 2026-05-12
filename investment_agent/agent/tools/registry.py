from .base import BaseTool
from .market_data import StockInfoTool, StockPriceTool, StockRealtimeTool, MarketIndexTool
from .financials import (
    IncomeStatementTool, BalanceSheetTool, CashFlowTool,
    ValuationTool, FinancialIndicatorTool,
)
from .run_command import RunCommandTool

_registry: dict[str, BaseTool] = {}


def _register(tool: BaseTool) -> None:
    _registry[tool.name] = tool


# register all built-in tools
_register(StockInfoTool())
_register(StockPriceTool())
_register(StockRealtimeTool())
_register(MarketIndexTool())
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
    return [t.schema for t in _registry.values()]
