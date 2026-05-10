import asyncio
import json
from .base import BaseTool


def _run_sync(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


class IncomeStatementTool(BaseTool):
    name = "get_income_statement"
    description = "获取A股上市公司利润表数据，包括营收、净利润、毛利率等核心指标。"
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码，如 '600519'"},
                },
                "required": ["symbol"],
            },
        }

    async def run(self, symbol: str) -> str:
        import akshare as ak
        try:
            df = await _run_sync(ak.stock_financial_report_sina, stock=symbol, symbol="利润表")
            df = df.head(8)
            return df.to_string(index=False)
        except Exception as e:
            return f"获取利润表失败: {e}"


class BalanceSheetTool(BaseTool):
    name = "get_balance_sheet"
    description = "获取A股上市公司资产负债表，包括总资产、负债、净资产等。"
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码，如 '600519'"},
                },
                "required": ["symbol"],
            },
        }

    async def run(self, symbol: str) -> str:
        import akshare as ak
        try:
            df = await _run_sync(ak.stock_financial_report_sina, stock=symbol, symbol="资产负债表")
            df = df.head(8)
            return df.to_string(index=False)
        except Exception as e:
            return f"获取资产负债表失败: {e}"


class CashFlowTool(BaseTool):
    name = "get_cash_flow"
    description = "获取A股上市公司现金流量表，包括经营/投资/筹资活动现金流。"
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码，如 '600519'"},
                },
                "required": ["symbol"],
            },
        }

    async def run(self, symbol: str) -> str:
        import akshare as ak
        try:
            df = await _run_sync(ak.stock_financial_report_sina, stock=symbol, symbol="现金流量表")
            df = df.head(8)
            return df.to_string(index=False)
        except Exception as e:
            return f"获取现金流量表失败: {e}"


class ValuationTool(BaseTool):
    name = "get_valuation"
    description = "获取A股股票估值指标，包括PE、PB、PS、股息率等。"
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码，如 '600519'"},
                },
                "required": ["symbol"],
            },
        }

    async def run(self, symbol: str) -> str:
        import akshare as ak
        try:
            df = await _run_sync(ak.stock_a_lg_indicator, symbol=symbol)
            df = df.tail(10)
            return df.to_string(index=False)
        except Exception as e:
            return f"获取估值指标失败: {e}"


class FinancialIndicatorTool(BaseTool):
    name = "get_financial_indicators"
    description = "获取A股股票核心财务指标，包括ROE、ROA、毛利率、净利率等。"
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码，如 '600519'"},
                },
                "required": ["symbol"],
            },
        }

    async def run(self, symbol: str) -> str:
        import akshare as ak
        try:
            df = await _run_sync(ak.stock_financial_analysis_indicator, symbol=symbol, start_year="2020")
            df = df.head(12)
            return df.to_string(index=False)
        except Exception as e:
            return f"获取财务指标失败: {e}"
