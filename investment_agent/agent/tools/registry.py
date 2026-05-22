from .base import BaseTool
from .market_data import StockInfoTool, StockPriceTool
# StockRealtimeTool, MarketIndexTool 已注释：依赖 eastmoney.com API，网络不通
from .financials import (
    IncomeStatementTool, BalanceSheetTool, CashFlowTool,
    ValuationTool, FinancialIndicatorTool,
)
from .run_command import RunCommandTool
from ..skills.tool import SkillTool

# 工具注册中心：单例字典存储所有已注册工具
_registry: dict[str, BaseTool] = {}


def _register(tool: BaseTool) -> None:
    _registry[tool.name] = tool


# —— 启动时注册所有内置工具 ——
_register(SkillTool())
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


# 始终自动绑定的基础设施工具（Skill 加载 + 命令执行）
AUTO_BOUND_TOOLS: set[str] = {"Skill", "run_command"}


def get_all_tools() -> list[BaseTool]:
    return list(_registry.values())


def get_all_tool_infos() -> list[dict]:
    """返回所有已注册工具的元信息（供前端展示）"""
    return [
        {
            "name": t.name,
            "description": t.description,
            "auto_bound": t.name in AUTO_BOUND_TOOLS,
        }
        for t in _registry.values()
    ]


def get_tool(name: str) -> BaseTool | None:
    return _registry.get(name)


def get_schemas() -> list[dict]:
    """返回所有工具的 Anthropic tool schema 列表，用于注入 LLM 请求"""
    return [t.schema for t in _registry.values()]


def get_schemas_for_names(names: set[str]) -> list[dict]:
    """只返回指定名称的工具 schema"""
    return [t.schema for t in _registry.values() if t.name in names]
