#!/usr/bin/env python3
"""A股股票行情与基本信息查询脚本。"""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _run_sync(func, *args, **kwargs):
    """在线程池中执行同步函数，避免阻塞事件循环（AKShare 不支持 async）。"""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


async def _get_stock_info(symbol: str) -> str:
    import akshare as ak
    try:
        df = await _run_sync(ak.stock_individual_info_em, symbol=symbol)
        result = {row["item"]: row["value"] for _, row in df.iterrows()}
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"获取股票信息失败: {e}"


async def _get_stock_price(symbol: str, period: str = "daily", count: int = 30) -> str:
    import akshare as ak
    try:
        df = await _run_sync(ak.stock_zh_a_hist, symbol=symbol, period=period, adjust="qfq")
        df = df.tail(count)
        df.columns = [c.strip() for c in df.columns]
        return df.to_string(index=False)
    except Exception as e:
        return f"获取行情数据失败: {e}"


async def _get_stock_realtime(symbol: str) -> str:
    import akshare as ak
    try:
        df = await _run_sync(ak.stock_zh_a_spot_em)
        row = df[df["代码"] == symbol]
        if row.empty:
            return f"未找到股票 {symbol} 的实时数据"
        return row.iloc[0].to_json(force_ascii=False)
    except Exception as e:
        return f"获取实时行情失败: {e}"


async def _get_market_index(symbol: str, count: int = 20) -> str:
    import akshare as ak
    try:
        df = await _run_sync(ak.index_zh_a_hist, symbol=symbol, period="daily")
        df = df.tail(count)
        return df.to_string(index=False)
    except Exception as e:
        return f"获取指数数据失败: {e}"


_HANDLERS = {
    "get_stock_info": _get_stock_info,
    "get_stock_price": _get_stock_price,
    "get_stock_realtime": _get_stock_realtime,
    "get_market_index": _get_market_index,
}


def main():
    parser = argparse.ArgumentParser(description="A股股票行情与基本信息查询")
    parser.add_argument(
        "--action", required=True,
        choices=list(_HANDLERS.keys()),
        help="操作类型"
    )
    parser.add_argument("--symbol", required=True, help="股票代码，如 600519")
    parser.add_argument("--period", default="daily", choices=["daily", "weekly", "monthly"], help="行情周期（默认 daily）")
    parser.add_argument("--count", type=int, default=30, help="返回数据条数（默认 30）")
    args = parser.parse_args()

    handler = _HANDLERS[args.action]
    result = asyncio.run(handler(args.symbol, args.period, args.count))
    print(result)


if __name__ == "__main__":
    main()
