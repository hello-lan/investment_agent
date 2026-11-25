#!/usr/bin/env python3
"""A股上市公司行情与财务数据查询脚本。"""

import argparse
import asyncio
import inspect
import json
import time
from datetime import datetime, timedelta
from pathlib import Path


def _run_sync(func, *args, **kwargs):
    """在线程池中执行同步函数，避免阻塞事件循环（AKShare 不支持 async）。"""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


# ── 行情 / 基本信息 ──────────────────────────────────────────

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


# ── 财务报表 / 估值 / 指标 ────────────────────────────────────

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


async def _get_dividend_history(symbol: str) -> str:
    """历史分红配送详情（东方财富）。"""
    import akshare as ak
    try:
        df = await _run_sync(ak.stock_fhps_detail_em, symbol=symbol)
        if df is None or df.empty:
            return f"未找到 {symbol} 的历史分红数据"
        return df.to_string(index=False)
    except Exception as e:
        return f"获取历史分红失败: {e}"


_REPURCHASE_CACHE_TTL = 24 * 3600  # 全市场回购接口较慢，本地缓存 24h
_REPURCHASE_CACHE = Path(__file__).resolve().parent / ".cache" / "repurchase_em.pkl"


def _load_repurchase_cache():
    import pickle

    if not _REPURCHASE_CACHE.exists():
        return None
    try:
        with _REPURCHASE_CACHE.open("rb") as f:
            payload = pickle.load(f)
        if time.time() - payload.get("ts", 0) > _REPURCHASE_CACHE_TTL:
            return None
        return payload.get("df")
    except Exception:
        return None


def _save_repurchase_cache(df) -> None:
    import pickle

    try:
        _REPURCHASE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with _REPURCHASE_CACHE.open("wb") as f:
            pickle.dump({"ts": time.time(), "df": df}, f)
    except Exception:
        pass


async def _get_share_repurchase(symbol: str) -> str:
    """股票回购（东方财富全市场接口，按代码过滤）。"""
    import akshare as ak

    try:
        df = _load_repurchase_cache()
        if df is None:
            df = await _run_sync(ak.stock_repurchase_em)
            _save_repurchase_cache(df)

        code_col = "股票代码" if "股票代码" in df.columns else "代码"
        matched = df[df[code_col].astype(str) == str(symbol)]
        if matched.empty:
            return f"未找到 {symbol} 的股票回购记录"
        return matched.to_string(index=False)
    except Exception as e:
        return f"获取股票回购失败: {e}"


async def _get_company_dynamics(symbol: str) -> str:
    """公司动态：近一年个股公告（东方财富）。"""
    import akshare as ak

    try:
        end = datetime.now().strftime("%Y%m%d")
        begin = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        df = await _run_sync(
            ak.stock_individual_notice_report,
            security=symbol,
            symbol="全部",
            begin_date=begin,
            end_date=end,
        )
        if df is None or df.empty:
            return f"未找到 {symbol} 近一年的公司公告/动态"
        return df.head(30).to_string(index=False)
    except Exception as e:
        return f"获取公司动态失败: {e}"


_HANDLERS = {
    # 行情 / 基本信息
    "get_stock_info": _get_stock_info,
    "get_stock_price": _get_stock_price,
    "get_stock_realtime": _get_stock_realtime,
    "get_market_index": _get_market_index,
    # 财务报表 / 估值 / 指标
    "get_income_statement": _get_income_statement,
    "get_balance_sheet": _get_balance_sheet,
    "get_cash_flow": _get_cash_flow,
    "get_valuation": _get_valuation,
    "get_financial_indicators": _get_financial_indicators,
    "get_dividend_history": _get_dividend_history,
    "get_share_repurchase": _get_share_repurchase,
    "get_company_dynamics": _get_company_dynamics,
}


def main():
    parser = argparse.ArgumentParser(description="A股上市公司行情与财务数据查询")
    parser.add_argument(
        "--action", required=True,
        choices=list(_HANDLERS.keys()),
        help="操作类型"
    )
    parser.add_argument("--symbol", required=True, help="股票/指数代码，如 600519")
    parser.add_argument(
        "--period", default="daily", choices=["daily", "weekly", "monthly"],
        help="行情周期（仅 get_stock_price，默认 daily）",
    )
    parser.add_argument(
        "--count", type=int, default=30,
        help="返回数据条数（仅行情/指数类 action，默认 30）",
    )
    args = parser.parse_args()

    handler = _HANDLERS[args.action]
    kwargs = {"symbol": args.symbol}
    params = inspect.signature(handler).parameters
    if "period" in params:
        kwargs["period"] = args.period
    if "count" in params:
        kwargs["count"] = args.count

    result = asyncio.run(handler(**kwargs))
    print(result)


if __name__ == "__main__":
    main()
