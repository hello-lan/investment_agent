#!/usr/bin/env python3
"""A股同业对比分析脚本。"""

import argparse
import asyncio
import json
import math


def _em_symbol(code: str) -> str:
    return f"SH{code}" if code.startswith("6") else f"SZ{code}"


def _run_sync(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: func(*args, **kwargs))


def _safe_float(v):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


async def _fetch_indicators(symbol: str) -> dict | None:
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
    import akshare as ak

    symbol_em = _em_symbol(symbol)
    try:
        df = await _run_sync(ak.stock_zh_valuation_comparison_em, symbol=symbol_em)
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


async def run_compare(symbol: str, action: str, peer_count: int = 5) -> dict:
    val_data = await _fetch_peers_from_valuation(symbol, peer_count + 5)
    if "error" in val_data:
        return val_data

    target_ind = await _fetch_indicators(symbol)
    peers = val_data.get("peers", [])
    # 排除自身
    peers = [p for p in peers if p["code"] != symbol][:peer_count]

    enriched_peers = []
    for p in peers:
        ind = await _fetch_indicators(p["code"])
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
    }

    if action == "compare":
        result["deviations"] = deviations
        if deviations:
            result["summary"] = "；".join(d["note"] for d in deviations[:5])
        else:
            result["summary"] = "关键指标与同业均值无明显偏离"

    return result


def main():
    parser = argparse.ArgumentParser(description="A股同业对比")
    parser.add_argument("--action", required=True, choices=["compare", "list_peers"])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--peer-count", type=int, default=5)
    args = parser.parse_args()

    result = asyncio.run(run_compare(args.symbol.strip(), args.action, args.peer_count))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
