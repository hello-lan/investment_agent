#!/usr/bin/env python3
"""A股上市公司财务数据查询脚本。"""

import argparse
import asyncio
import sys
from pathlib import Path


def _run_sync(func, *args, **kwargs):
    """在线程池中执行同步函数，避免阻塞事件循环（AKShare 不支持 async）。"""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


async def _get_income_statement(symbol: str) -> str:
    import akshare as ak
    try:
        df = await _run_sync(ak.stock_financial_report_sina, stock=symbol, symbol="利润表")
        df = df.head(8)
        return df.to_string(index=False)
    except Exception as e:
        return f"获取利润表失败: {e}"


async def _get_balance_sheet(symbol: str) -> str:
    import akshare as ak
    try:
        df = await _run_sync(ak.stock_financial_report_sina, stock=symbol, symbol="资产负债表")
        df = df.head(8)
        return df.to_string(index=False)
    except Exception as e:
        return f"获取资产负债表失败: {e}"


async def _get_cash_flow(symbol: str) -> str:
    import akshare as ak
    try:
        df = await _run_sync(ak.stock_financial_report_sina, stock=symbol, symbol="现金流量表")
        df = df.head(8)
        return df.to_string(index=False)
    except Exception as e:
        return f"获取现金流量表失败: {e}"


async def _get_valuation(symbol: str) -> str:
    import akshare as ak
    try:
        if symbol.startswith("6"):
            full_symbol = f"SH{symbol}"
        elif symbol.startswith(("0", "3")):
            full_symbol = f"SZ{symbol}"
        else:
            full_symbol = symbol
        df = await _run_sync(ak.stock_zh_valuation_comparison_em, symbol=full_symbol)
        return df.to_string(index=False)
    except Exception as e:
        return f"获取估值指标失败: {e}"


async def _get_financial_indicators(symbol: str) -> str:
    import akshare as ak
    try:
        df = await _run_sync(ak.stock_financial_analysis_indicator, symbol=symbol, start_year="2020")
        df = df.head(12)
        return df.to_string(index=False)
    except Exception as e:
        return f"获取财务指标失败: {e}"


_HANDLERS = {
    "get_income_statement": _get_income_statement,
    "get_balance_sheet": _get_balance_sheet,
    "get_cash_flow": _get_cash_flow,
    "get_valuation": _get_valuation,
    "get_financial_indicators": _get_financial_indicators,
}


def main():
    parser = argparse.ArgumentParser(description="A股上市公司财务数据查询")
    parser.add_argument(
        "--action", required=True,
        choices=list(_HANDLERS.keys()),
        help="操作类型"
    )
    parser.add_argument("--symbol", required=True, help="股票代码，如 600519")
    args = parser.parse_args()

    handler = _HANDLERS[args.action]
    result = asyncio.run(handler(args.symbol))
    print(result)


if __name__ == "__main__":
    main()
