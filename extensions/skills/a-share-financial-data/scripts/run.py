#!/usr/bin/env python3
"""A股上市公司行情与财务数据查询脚本。"""

import argparse
import asyncio
import inspect
import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

_PEER_COUNT_MAX = 10


def _run_sync(func, *args, **kwargs):
    """在线程池中执行同步函数，避免阻塞事件循环（AKShare 不支持 async）。"""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


def _em_symbol(code: str) -> str:
    if code.startswith("6"):
        return f"SH{code}"
    if code.startswith(("0", "3")):
        return f"SZ{code}"
    return code


def _safe_float(v):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _clamp_peer_count(peer_count: int) -> int:
    return max(1, min(int(peer_count), _PEER_COUNT_MAX))

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
        df = await _run_sync(ak.stock_zh_valuation_comparison_em, symbol=_em_symbol(symbol))
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


# ── 同业对比（衍生 action）────────────────────────────────────

async def _fetch_peer_indicators(symbol: str) -> dict | None:
    """取最近年报（或最新一期）关键财务指标。"""
    import akshare as ak

    try:
        df = await _run_sync(ak.stock_financial_analysis_indicator, symbol=symbol, start_year="2023")
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    annual = df[df["日期"].astype(str).str.endswith("-12-31")]
    if len(annual) == 0:
        row = df.sort_values("日期").iloc[-1]
    else:
        row = annual.sort_values("日期").iloc[-1]
    return {
        "report_date": str(row.get("日期", ""))[:10],
        "roe": _safe_float(row.get("净资产收益率(%)")),
        "gross_margin": _safe_float(row.get("销售毛利率(%)")),
        "net_margin": _safe_float(row.get("销售净利率(%)")),
        "debt_ratio": _safe_float(row.get("资产负债率(%)")),
        "cfnp": _safe_float(row.get("经营现金净流量与净利润的比率(%)")),
        "revenue_yoy": _safe_float(row.get("主营业务收入增长率(%)")),
        "net_profit_yoy": _safe_float(row.get("净利润增长率(%)")),
    }


async def _fetch_peers_from_valuation(symbol: str, peer_count: int) -> dict:
    """从东财估值对比表解析可比公司与行业均值。"""
    import akshare as ak

    try:
        df = await _run_sync(ak.stock_zh_valuation_comparison_em, symbol=_em_symbol(symbol))
    except Exception as e:
        return {"error": str(e), "peers": []}

    if df is None or len(df) == 0:
        return {"peers": []}

    target_name = str(df.iloc[0].iloc[2]) if len(df.iloc[0]) > 2 else symbol
    industry_avg = None
    peers = []

    for _, row in df.iterrows():
        col1 = str(row.iloc[1]) if len(row) > 1 else ""
        if col1 in ("行业均值", "行业平均"):
            industry_avg = {
                "pe_ttm": _safe_float(row.iloc[4]) if len(row) > 4 else None,
                "pb": _safe_float(row.iloc[14]) if len(row) > 14 else None,
                "revenue_growth": _safe_float(row.iloc[8]) if len(row) > 8 else None,
            }
            continue
        if col1 in ("行业市值", "行业均值", "行业平均"):
            continue
        rank = row.iloc[0]
        if rank is None or (isinstance(rank, float) and math.isnan(rank)):
            continue
        code = str(row.iloc[1]).strip()
        if not code.isdigit() or len(code) != 6:
            continue
        peers.append({
            "code": code,
            "name": str(row.iloc[2]) if len(row) > 2 else "",
            "pe_ttm": _safe_float(row.iloc[4]) if len(row) > 4 else None,
            "pb": _safe_float(row.iloc[14]) if len(row) > 14 else None,
            "revenue_growth": _safe_float(row.iloc[8]) if len(row) > 8 else None,
            "net_profit_growth": _safe_float(row.iloc[9]) if len(row) > 9 else None,
        })

    return {
        "target_name": target_name,
        "industry_avg": industry_avg,
        "peers": peers[:peer_count],
    }


def _detect_deviations(target: dict, industry_avg: dict | None, peers: list[dict]) -> list[dict]:
    deviations = []
    if not industry_avg:
        return deviations

    checks = [
        ("roe", "ROE", "percentage", True),
        ("gross_margin", "毛利率", "percentage", True),
        ("debt_ratio", "资产负债率", "percentage", False),
        ("cfnp", "经营现金流/净利润", "percentage", True),
    ]

    for key, label, unit, higher_better in checks:
        t_val = target.get(key)
        if t_val is None:
            continue
        peer_vals = [p.get(key) for p in peers if p.get(key) is not None]
        if not peer_vals:
            continue
        avg = sum(peer_vals) / len(peer_vals)
        diff = t_val - avg
        threshold = abs(avg) * 0.25 if avg else 5
        if abs(diff) < threshold:
            continue
        direction = "高于" if diff > 0 else "低于"
        flag = "positive" if (diff > 0) == higher_better else "negative"
        deviations.append({
            "metric": label,
            "target": round(t_val, 2),
            "peer_avg": round(avg, 2),
            "deviation": round(diff, 2),
            "direction": direction,
            "flag": flag,
            "note": f"{label}{direction}同业均值 {abs(round(diff, 1))}{'%' if unit == 'percentage' else ''}",
        })
    return deviations


async def _list_peers(symbol: str, peer_count: int = 5) -> str:
    """列出行业可比公司（仅估值对比表，不逐家补财务指标）。"""
    peer_count = _clamp_peer_count(peer_count)
    val_data = await _fetch_peers_from_valuation(symbol, peer_count + 5)
    if "error" in val_data:
        return json.dumps(val_data, ensure_ascii=False, indent=2)

    peers = [p for p in val_data.get("peers", []) if p["code"] != symbol][:peer_count]
    result = {
        "symbol": symbol,
        "target_name": val_data.get("target_name", symbol),
        "industry_avg": val_data.get("industry_avg"),
        "peers": peers,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


async def _compare_peers(symbol: str, peer_count: int = 5) -> str:
    """与同业对比关键财务指标，并标注异常偏离。"""
    peer_count = _clamp_peer_count(peer_count)
    val_data = await _fetch_peers_from_valuation(symbol, peer_count + 5)
    if "error" in val_data:
        return json.dumps(val_data, ensure_ascii=False, indent=2)

    target_ind = await _fetch_peer_indicators(symbol)
    peers = [p for p in val_data.get("peers", []) if p["code"] != symbol][:peer_count]

    enriched_peers = []
    for p in peers:
        ind = await _fetch_peer_indicators(p["code"])
        enriched_peers.append({**p, **(ind or {})})

    target = {
        "code": symbol,
        "name": val_data.get("target_name", symbol),
        **(target_ind or {}),
        **(val_data.get("industry_avg") or {}),
    }
    deviations = _detect_deviations(
        target_ind or {},
        val_data.get("industry_avg"),
        enriched_peers,
    )

    result = {
        "symbol": symbol,
        "target": target,
        "industry_avg": val_data.get("industry_avg"),
        "peers": enriched_peers,
        "deviations": deviations,
        "summary": (
            "；".join(d["note"] for d in deviations[:5])
            if deviations
            else "关键指标与同业均值无明显偏离"
        ),
    }
    return json.dumps(result, ensure_ascii=False, indent=2)

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
    # 同业对比
    "list_peers": _list_peers,
    "compare_peers": _compare_peers,
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
    parser.add_argument(
        "--peer-count", type=int, default=5,
        help=f"同业对比公司数量（仅 list_peers/compare_peers，默认 5，上限 {_PEER_COUNT_MAX}）",
    )
    args = parser.parse_args()

    handler = _HANDLERS[args.action]
    kwargs = {"symbol": args.symbol}
    params = inspect.signature(handler).parameters
    if "period" in params:
        kwargs["period"] = args.period
    if "count" in params:
        kwargs["count"] = args.count
    if "peer_count" in params:
        kwargs["peer_count"] = args.peer_count

    result = asyncio.run(handler(**kwargs))
    print(result)

if __name__ == "__main__":
    main()
