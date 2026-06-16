#!/usr/bin/env python3
"""A股估值分析脚本 — DCF / 相对估值 / 周期股调整。"""

import argparse
import asyncio
import json
import math
import sys


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


def _parse_amount(raw) -> float | None:
    """解析金额，统一为元"""
    v = _safe_float(raw)
    return v


async def _fetch_annual_series(symbol: str, years: int = 10) -> list[dict]:
    import akshare as ak

    symbol_em = _em_symbol(symbol)
    ind_df, cf_df, inc_df = await asyncio.gather(
        _run_sync(ak.stock_financial_analysis_indicator, symbol=symbol, start_year=str(2020)),
        _run_sync(ak.stock_cash_flow_sheet_by_report_em, symbol_em),
        _run_sync(ak.stock_profit_sheet_by_report_em, symbol_em),
    )

    cf_by_date = {}
    if cf_df is not None and len(cf_df):
        for _, row in cf_df.iterrows():
            rd = str(row.get("REPORT_DATE", ""))[:10]
            if rd.endswith("-12-31"):
                cf_by_date[rd] = row

    inc_by_date = {}
    if inc_df is not None and len(inc_df):
        for _, row in inc_df.iterrows():
            rd = str(row.get("REPORT_DATE", ""))[:10]
            if rd.endswith("-12-31"):
                inc_by_date[rd] = row

    records = []
    if ind_df is None or len(ind_df) == 0:
        return records

    sorted_df = ind_df.sort_values("日期")
    for _, row in sorted_df.iterrows():
        rd = str(row.get("日期", ""))[:10]
        if not rd.endswith("-12-31"):
            continue
        cf = cf_by_date.get(rd, {})
        inc = inc_by_date.get(rd, {})
        ocf = _parse_amount(cf.get("NETCASH_OPERATE") if hasattr(cf, "get") else None)
        capex = _parse_amount(cf.get("CONSTRUCT_LONG_ASSET") if hasattr(cf, "get") else None)
        revenue = _parse_amount(inc.get("OPERATE_INCOME") if hasattr(inc, "get") else None)
        if revenue is None:
            revenue = _parse_amount(row.get("主营业务收入(元)"))
        net_profit = _parse_amount(inc.get("PARENT_NETPROFIT") if hasattr(inc, "get") else None)
        if net_profit is None:
            net_profit = _parse_amount(row.get("净利润(元)"))
        records.append({
            "report_date": rd,
            "revenue": revenue,
            "net_profit": net_profit,
            "ocf": ocf,
            "capex": capex,
            "fcf": (ocf - abs(capex)) if ocf is not None and capex is not None else None,
            "cfnp": (
                ocf / net_profit * 100
                if ocf is not None and net_profit and net_profit != 0
                else _safe_float(row.get("经营现金净流量与净利润的比率(%)"))
            ),
            "eps": _safe_float(row.get("摊薄每股收益(元)")),
            "roe": _safe_float(row.get("净资产收益率(%)")),
            "gross_margin": _safe_float(row.get("销售毛利率(%)")),
            "debt_ratio": _safe_float(row.get("资产负债率(%)")),
        })

    return records[-years:]


async def _fetch_valuation(symbol: str) -> dict:
    import akshare as ak

    symbol_em = _em_symbol(symbol)
    try:
        df = await _run_sync(ak.stock_zh_valuation_comparison_em, symbol=symbol_em)
    except Exception as e:
        return {"error": str(e)}

    if df is None or len(df) == 0:
        return {}

    result = {"peers": [], "industry_avg": None}
    for _, row in df.iterrows():
        name = str(row.iloc[1]) if len(row) > 1 else ""
        if name in ("行业均值", "行业平均"):
            result["industry_avg"] = {
                "pe_ttm": _safe_float(row.iloc[4]) if len(row) > 4 else None,
                "pb": _safe_float(row.iloc[14]) if len(row) > 14 else None,
            }
        elif name and name not in ("行业均值", "行业平均", "行业市值") and str(row.iloc[0]).replace(".", "").isdigit():
            result["peers"].append({
                "rank": _safe_float(row.iloc[0]),
                "code": str(row.iloc[1]),
                "name": str(row.iloc[2]) if len(row) > 2 else "",
                "pe_ttm": _safe_float(row.iloc[4]) if len(row) > 4 else None,
                "pb": _safe_float(row.iloc[14]) if len(row) > 14 else None,
            })
    # 第一行通常是目标公司自身
    if len(df) > 0:
        self_row = df.iloc[0]
        result["self"] = {
            "pe_ttm": _safe_float(self_row.iloc[4]) if len(self_row) > 4 else None,
            "pb": _safe_float(self_row.iloc[14]) if len(self_row) > 14 else None,
            "peg": _safe_float(self_row.iloc[3]) if len(self_row) > 3 else None,
        }
    return result


async def _fetch_shares(symbol: str, records: list[dict]) -> float | None:
    """总股本：优先 EPS 反推，fallback 东财个股信息"""
    if records:
        latest = records[-1]
        np_val = latest.get("net_profit")
        eps = latest.get("eps")
        if np_val and eps and eps > 0:
            return np_val / eps

    import akshare as ak
    try:
        df = await _run_sync(ak.stock_individual_info_em, symbol=symbol)
        for _, row in df.iterrows():
            item = str(row.get("item", ""))
            if "总股本" in item or "流通股" in item:
                raw = str(row.get("value", "")).replace("股", "").replace(",", "").strip()
                val = _safe_float(raw)
                if val:
                    return val
    except Exception:
        pass
    return None


def _cagr(values: list[float], n: int) -> float | None:
    valid = [v for v in values if v and v > 0]
    if len(valid) < n + 1:
        return None
    start, end = valid[-(n + 1)], valid[-1]
    if start <= 0:
        return None
    return pow(end / start, 1 / n) - 1


def _is_cyclical(records: list[dict]) -> bool:
    profits = [r["net_profit"] for r in records if r.get("net_profit")]
    if len(profits) < 5:
        return False
    mean_p = sum(profits) / len(profits)
    if mean_p <= 0:
        return False
    cv = (sum((p - mean_p) ** 2 for p in profits) / len(profits)) ** 0.5 / abs(mean_p)
    return cv > 0.5


def _compute_dcf(
    records: list[dict],
    shares: float | None,
    discount_rate: float,
    terminal_growth: float,
    growth_years: int,
) -> dict:
    if not records or not shares or shares <= 0:
        return {"error": "数据不足，无法计算 DCF"}

    fcfs = [r["fcf"] for r in records if r.get("fcf") is not None]
    if len(fcfs) < 2:
        return {"error": "自由现金流数据不足"}

    latest_fcf = fcfs[-1]
    rev_cagr = _cagr([r["revenue"] for r in records if r.get("revenue")], 3)
    base_growth = rev_cagr if rev_cagr is not None else 0.05
    base_growth = max(-0.05, min(base_growth, 0.20))

    scenarios = {
        "optimistic": base_growth * 1.3,
        "neutral": base_growth,
        "pessimistic": base_growth * 0.5,
    }

    result = {}
    for name, g in scenarios.items():
        pv = 0.0
        fcf = latest_fcf
        for t in range(1, growth_years + 1):
            fcf *= (1 + g)
            pv += fcf / pow(1 + discount_rate, t)
        terminal = fcf * (1 + terminal_growth) / (discount_rate - terminal_growth)
        pv += terminal / pow(1 + discount_rate, growth_years)
        result[name] = {
            "growth_rate": round(g * 100, 2),
            "enterprise_value_yi": round(pv / 1e8, 2),
            "value_per_share": round(pv / shares, 2),
        }

    return {
        "latest_fcf_yi": round(latest_fcf / 1e8, 2),
        "base_revenue_cagr_pct": round((rev_cagr or 0) * 100, 2),
        "discount_rate_pct": round(discount_rate * 100, 2),
        "terminal_growth_pct": round(terminal_growth * 100, 2),
        "scenarios": result,
    }


def _compute_cycle_adjusted(records: list[dict], shares: float | None, pe_reasonable: float = 15) -> dict:
    profits = [r["net_profit"] for r in records if r.get("net_profit")]
    if len(profits) < 3 or not shares:
        return {"applicable": False}
    avg_profit = sum(profits) / len(profits)
    return {
        "applicable": True,
        "avg_net_profit_yi": round(avg_profit / 1e8, 2),
        "years": len(profits),
        "reasonable_pe": pe_reasonable,
        "implied_market_cap_yi": round(avg_profit * pe_reasonable / 1e8, 2),
        "implied_value_per_share": round(avg_profit * pe_reasonable / shares, 2),
        "note": "周期股应使用多年平均利润而非景气高点利润",
    }


def _assess_premises(records: list[dict]) -> dict:
    if not records:
        return {"profit_real": "unknown", "sustainable": "unknown", "low_capex": "unknown"}
    latest = records[-1]
    cfnp = latest.get("cfnp")
    profit_real = "pass" if cfnp is not None and cfnp >= 80 else ("warn" if cfnp is not None and cfnp >= 50 else "fail")
    roe_vals = [r["roe"] for r in records if r.get("roe") is not None]
    sustainable = "pass" if roe_vals and sum(roe_vals) / len(roe_vals) >= 10 else "warn"
    fcf_positive = sum(1 for r in records if r.get("fcf") and r["fcf"] > 0)
    low_capex = "pass" if fcf_positive >= len(records) * 0.6 else "warn"
    confidence = "high" if all(x == "pass" for x in [profit_real, sustainable, low_capex]) else "medium"
    if profit_real == "fail":
        confidence = "low"
    return {
        "profit_real": profit_real,
        "sustainable": sustainable,
        "low_capex": low_capex,
        "confidence": confidence,
        "cfnp_latest": cfnp,
    }


async def run_valuation(
    symbol: str,
    action: str,
    discount_rate: float = 0.10,
    terminal_growth: float = 0.025,
    growth_years: int = 5,
) -> dict:
    records = await _fetch_annual_series(symbol)
    shares = await _fetch_shares(symbol, records)
    premises = _assess_premises(records)

    output: dict = {"symbol": symbol, "premises": premises}

    if action in ("dcf", "full_valuation"):
        output["dcf"] = _compute_dcf(records, shares, discount_rate, terminal_growth, growth_years)

    if action in ("relative", "full_valuation"):
        output["relative"] = await _fetch_valuation(symbol)

    if action in ("cycle_adjusted", "full_valuation"):
        cyclical = _is_cyclical(records)
        output["is_cyclical"] = cyclical
        if cyclical or action == "cycle_adjusted":
            output["cycle_adjusted"] = _compute_cycle_adjusted(records, shares)

    if action == "full_valuation":
        dcf = output.get("dcf", {})
        scenarios = dcf.get("scenarios", {})
        if scenarios:
            low = scenarios.get("pessimistic", {}).get("value_per_share")
            high = scenarios.get("optimistic", {}).get("value_per_share")
            output["summary"] = (
                f"估值前提置信度：{premises.get('confidence')}。"
                f"DCF 三情景每股价值区间：{low} ~ {high} 元（非交易建议）。"
            )
        else:
            output["summary"] = f"估值前提置信度：{premises.get('confidence')}。DCF 数据不足，请参考相对估值。"

    return output


def main():
    parser = argparse.ArgumentParser(description="A股估值分析")
    parser.add_argument("--action", required=True,
                        choices=["full_valuation", "dcf", "relative", "cycle_adjusted"])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--discount-rate", type=float, default=0.10)
    parser.add_argument("--terminal-growth", type=float, default=0.025)
    parser.add_argument("--growth-years", type=int, default=5)
    args = parser.parse_args()

    result = asyncio.run(run_valuation(
        args.symbol.strip(),
        args.action,
        args.discount_rate,
        args.terminal_growth,
        args.growth_years,
    ))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
