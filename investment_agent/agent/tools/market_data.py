import asyncio
import json
from functools import lru_cache
from .base import BaseTool


def _run_sync(func, *args, **kwargs):
    """Run a sync function in a thread pool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


class StockInfoTool(BaseTool):
    name = "get_stock_info"
    description = "获取A股股票基本信息，包括股票名称、行业、市值等。输入股票代码（如 '600519' 或 '000001'）。"
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码，如 '600519'"}
                },
                "required": ["symbol"],
            },
        }

    async def run(self, symbol: str) -> str:
        import akshare as ak
        try:
            df = await _run_sync(ak.stock_individual_info_em, symbol=symbol)
            result = {row["item"]: row["value"] for _, row in df.iterrows()}
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"获取股票信息失败: {e}"


class StockPriceTool(BaseTool):
    name = "get_stock_price"
    description = "获取A股股票历史行情数据（日K线）。返回最近N个交易日的开高低收量数据。"
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
                    "period": {"type": "string", "description": "周期：daily/weekly/monthly，默认 daily", "default": "daily"},
                    "count": {"type": "integer", "description": "返回最近N条数据，默认30", "default": 30},
                },
                "required": ["symbol"],
            },
        }

    async def run(self, symbol: str, period: str = "daily", count: int = 30) -> str:
        import akshare as ak
        try:
            df = await _run_sync(
                ak.stock_zh_a_hist,
                symbol=symbol,
                period=period,
                adjust="qfq",
            )
            df = df.tail(count)
            df.columns = [c.strip() for c in df.columns]
            return df.to_string(index=False)
        except Exception as e:
            return f"获取行情数据失败: {e}"


class StockRealtimeTool(BaseTool):
    name = "get_stock_realtime"
    description = "获取A股股票实时行情，包括当前价格、涨跌幅、成交量等。"
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码，如 '600519'"}
                },
                "required": ["symbol"],
            },
        }

    async def run(self, symbol: str) -> str:
        import akshare as ak
        try:
            df = await _run_sync(ak.stock_zh_a_spot_em)
            row = df[df["代码"] == symbol]
            if row.empty:
                return f"未找到股票 {symbol} 的实时数据"
            return row.iloc[0].to_json(force_ascii=False)
        except Exception as e:
            return f"获取实时行情失败: {e}"


class MarketIndexTool(BaseTool):
    name = "get_market_index"
    description = "获取主要市场指数行情，如上证指数(000001)、深证成指(399001)、创业板指(399006)。"
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "指数代码，如 '000001'"},
                    "count": {"type": "integer", "description": "返回最近N条数据，默认20", "default": 20},
                },
                "required": ["symbol"],
            },
        }

    async def run(self, symbol: str, count: int = 20) -> str:
        import akshare as ak
        try:
            df = await _run_sync(ak.index_zh_a_hist, symbol=symbol, period="daily", adjust="")
            df = df.tail(count)
            return df.to_string(index=False)
        except Exception as e:
            return f"获取指数数据失败: {e}"
