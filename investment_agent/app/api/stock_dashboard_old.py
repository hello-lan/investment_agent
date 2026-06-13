"""个股看板 API —— 搜索、数据查询、同步状态"""

import asyncio

from fastapi import APIRouter, Query

from ..db import get_db
from ..services.stock_data import (
    check_and_sync,
    get_stock_sync_status,
    sync_stock_data,
    _needs_update,
)

router = APIRouter(prefix="/api", tags=["stock-dashboard-old"])


# ── 股票搜索 ──────────────────────────────────────────────


@router.get("/stocks/search")
async def search_stocks(q: str = Query(..., min_length=1)):
    q = q.strip()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT code, name, industry, market_cap FROM stock_info WHERE code = ?",
            (q,),
        )
        exact = await cursor.fetchone()
        if exact:
            return {"results": [dict(exact)], "source": "db"}

        cursor = await db.execute(
            "SELECT code, name, industry, market_cap FROM stock_info "
            "WHERE code LIKE ? OR name LIKE ? LIMIT 10",
            (f"{q}%", f"%{q}%"),
        )
        rows = await cursor.fetchall()
        results = [dict(r) for r in rows]
        if results:
            return {"results": results, "source": "db"}

    return {"results": [], "source": "none"}


def _parse_float(v):
    import math
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


# ── 看板数据 ──────────────────────────────────────────────


@router.get("/stock-dashboard-old/{code}")
async def get_dashboard(code: str, years: int = Query(default=10, ge=1, le=20)):
    code = code.strip()
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT code, name, industry, market_cap, listed_date, updated_at FROM stock_info WHERE code = ?",
            (code,),
        )
        stock = await cursor.fetchone()

        if stock is None:
            asyncio.create_task(sync_stock_data(code))
            return {"status": "syncing", "code": code, "message": "首次加载，正在获取数据..."}

        stock_dict = dict(stock)
        needs = await _needs_update(code)

    if needs:
        existing = get_stock_sync_status(code)
        if existing["status"] != "syncing":
            asyncio.create_task(sync_stock_data(code))

    sections = await _build_dashboard(code, years)

    return {
        "status": "updating" if needs else "ready",
        "code": code,
        "stock": stock_dict,
        "sections": sections,
    }


@router.get("/stock-dashboard-old/{code}/status")
async def get_dashboard_status(code: str):
    status = get_stock_sync_status(code)
    return {"code": code, **status}


# ── 看板数据组装（从 DB 查询 → 模块化 JSON） ─────────────────


async def _has_table(db, table: str) -> bool:
    """检查表是否为空"""
    cursor = await db.execute(f"SELECT COUNT(*) FROM {table} LIMIT 1")
    row = await cursor.fetchone()
    return row[0] > 0


async def _build_dashboard(code: str, years: int) -> dict:
    sections = {}

    async with get_db() as db:

        # ── 快照 ──
        cursor = await db.execute(
            "SELECT report_date, eps, bvps, roe, roe_diluted, roa, debt_ratio, gross_margin, net_margin "
            "FROM stock_indicators WHERE code = ? ORDER BY report_date DESC LIMIT 1",
            (code,),
        )
        latest = await cursor.fetchone()
        if latest:
            sections["snapshot"] = dict(latest)

        # ── 1. 盈利能力 ──
        cursor = await db.execute(
            "SELECT report_date, gross_margin, net_margin, roe, roa "
            "FROM stock_indicators WHERE code = ? AND report_type = 'annual' ORDER BY report_date ASC",
            (code,),
        )
        rows = await cursor.fetchall()
        sections["profitability"] = {
            "chart": {
                "dates": [r["report_date"] for r in rows],
                "gross_margin": [r["gross_margin"] for r in rows],
                "net_margin": [r["net_margin"] for r in rows],
                "roe": [r["roe"] for r in rows],
                "roa": [r["roa"] for r in rows],
            },
            "thresholds": {"net_margin": 15, "roa": 6, "roe": 10},
        }

        # ── 2. ROE 拆解 ──
        cursor = await db.execute(
            "SELECT report_date, total_revenue, net_profit, total_asset_turnover, equity_multiplier, roe_diluted "
            "FROM stock_indicators WHERE code = ? AND report_type = 'annual' ORDER BY report_date DESC LIMIT ?",
            (code, years),
        )
        rows = await cursor.fetchall()
        roe_items = []
        for r in reversed(rows):
            npr = None
            if r["net_profit"] and r["total_revenue"] and r["total_revenue"] != 0:
                npr = (r["net_profit"] / r["total_revenue"]) * 100
            roe_items.append({
                "date": r["report_date"],
                "net_profit_rate": round(npr, 2) if npr else None,
                "turnover": round(r["total_asset_turnover"], 4) if r["total_asset_turnover"] else None,
                "leverage": round(r["equity_multiplier"], 4) if r["equity_multiplier"] else None,
                "roe": round(r["roe_diluted"], 2) if r["roe_diluted"] else None,
            })
        sections["roe_decomposition"] = {"table": roe_items}

        # ── 3. 五力分析（需要 balance 表，不可达时跳过） ──
        has_balance = await _has_table(db, "stock_balance")
        if has_balance:
            cursor = await db.execute(
                "SELECT i.report_date, i.gross_margin, i.total_revenue, "
                "COALESCE(b.accounts_rece, b.note_accounts_rece) AS account_receivable, b.prepayment AS pre_payment, "
                "b.accounts_payable, COALESCE(b.advance_receivables, 0) + COALESCE(b.contract_liab, 0) AS pre_receivable "
                "FROM stock_indicators i "
                "JOIN stock_balance b ON i.code = b.code AND i.report_date = b.report_date "
                "WHERE i.code = ? AND i.report_type = 'annual' "
                "ORDER BY i.report_date DESC LIMIT ?",
                (code, years),
            )
            rows = await cursor.fetchall()
            ff_items = []
            for r in reversed(rows):
                rev = r["total_revenue"]
                ff_items.append({
                    "date": r["report_date"],
                    "ar_ratio": round(r["account_receivable"] / rev * 100, 2) if rev and r["account_receivable"] else None,
                    "prepay_ratio": round(r["pre_payment"] / rev * 100, 2) if rev and r["pre_payment"] else None,
                    "ap_ratio": round(r["accounts_payable"] / rev * 100, 2) if rev and r["accounts_payable"] else None,
                    "pr_ratio": round(r["pre_receivable"] / rev * 100, 2) if rev and r["pre_receivable"] else None,
                    "gross_margin": round(r["gross_margin"], 2) if r["gross_margin"] else None,
                })
            sections["five_forces"] = {"table": ff_items}

        # ── 4. 自由现金流（用 cashflow 表的 netcash_operate） ──
        cursor = await db.execute(
            "SELECT i.report_date, i.cfr, i.cfnp, cf.netcash_operate AS operating_cf_raw "
            "FROM stock_indicators i "
            "LEFT JOIN stock_cashflow cf ON i.code = cf.code AND i.report_date = cf.report_date "
            "WHERE i.code = ? AND i.report_type = 'annual' ORDER BY i.report_date DESC LIMIT ?",
            (code, years),
        )
        rows = await cursor.fetchall()
        cf_items = []
        prev_cf = None
        for r in reversed(rows):
            cur_cf = _div100m(r["operating_cf_raw"])  # 转换为亿
            yoy = None
            if prev_cf and prev_cf != 0 and cur_cf is not None:
                yoy = round((cur_cf - prev_cf) / abs(prev_cf) * 100, 2)
            cf_items.append({
                "date": r["report_date"],
                "operating_cf": cur_cf,
                "cfr": round(r["cfr"], 2) if r["cfr"] else None,
                "cfnp": round(r["cfnp"], 2) if r["cfnp"] else None,
                "yoy": yoy,
            })
            prev_cf = cur_cf
        sections["free_cashflow"] = {"table": cf_items}

        # ── 5. 成长性 ──
        for key, label_field, yoy_field in [
            ("revenue", "total_revenue", "revenue_yoy"),
            ("net_profit_growth", "net_profit", "net_profit_yoy"),
            ("net_profit_adjusted", "net_profit_adjusted", "net_profit_adjusted_yoy"),
        ]:
            cursor = await db.execute(
                f"SELECT report_date, {label_field}, {yoy_field} "
                "FROM stock_indicators WHERE code = ? AND report_type = 'annual' ORDER BY report_date ASC",
                (code,),
            )
            rows = await cursor.fetchall()
            sections.setdefault("growth", {})[key] = {
                "dates": [r["report_date"] for r in rows],
                "values": [_div100m(r[label_field]) for r in rows],
                "yoy": [r[yoy_field] for r in rows],
                "label": {"revenue": "营业收入", "net_profit_growth": "净利润", "net_profit_adjusted": "扣非净利润"}[key],
            }

        # 净资产 & 总资产（从 balance 表，仅取年报）
        if has_balance:
            for bkey, label, balance_col in [
                ("holders_equity", "净资产", "total_equity"),
                ("total_assets", "总资产", "total_assets"),
            ]:
                cursor = await db.execute(
                    f"SELECT report_date, {balance_col} AS val FROM stock_balance "
                    "WHERE code = ? AND report_type = 'annual' ORDER BY report_date ASC",
                    (code,),
                )
                rows = await cursor.fetchall()
                sections.setdefault("growth", {})[bkey] = {
                    "dates": [r["report_date"] for r in rows],
                    "values": [_div100m(r["val"]) for r in rows],
                    "label": label,
                }

        # ── 6. 收益性（百分率利润表，需要 income 表） ──
        has_income = await _has_table(db, "stock_income")
        if has_income:
            cursor = await db.execute(
                "SELECT report_date, operate_income AS revenue, operate_cost AS operating_cost, "
                "sale_expense AS sales_fee, manage_expense AS manage_fee, "
                "research_expense AS rd_cost, finance_expense AS finance_fee "
                "FROM stock_income WHERE code = ? ORDER BY report_date DESC LIMIT ?",
                (code, years),
            )
            rows = await cursor.fetchall()
            ip_items = []
            for r in reversed(rows):
                rev = r["revenue"]
                if not rev:
                    continue
                oc = r["operating_cost"]
                ip_items.append({
                    "date": r["report_date"],
                    "gross_margin": round((rev - oc) / rev * 100, 2) if oc else None,
                    "manage_fee_pct": round(r["manage_fee"] / rev * 100, 2) if r["manage_fee"] else None,
                    "sales_fee_pct": round(r["sales_fee"] / rev * 100, 2) if r["sales_fee"] else None,
                    "rd_pct": round((r["rd_cost"] or 0) / rev * 100, 2),
                    "finance_pct": round((r["finance_fee"] or 0) / rev * 100, 2),
                })
            sections["income_percentage"] = {"table": ip_items}

        # ── 7. 营运能力 ──
        cursor = await db.execute(
            "SELECT report_date, ar_turnover, ar_turnover_days, inventory_turnover, "
            "inventory_turnover_days, fixed_asset_turnover, total_asset_turnover "
            "FROM stock_indicators WHERE code = ? AND report_type = 'annual' ORDER BY report_date DESC LIMIT ?",
            (code, years),
        )
        rows = await cursor.fetchall()
        sections["operation"] = {"table": [dict(r) for r in reversed(rows)]}

        # ── 8. 财务风险 ──
        if has_balance:
            cursor = await db.execute(
                "SELECT i.report_date, i.debt_ratio, i.equity_multiplier, i.equity_ratio, "
                "i.current_ratio, i.quick_ratio, "
                "COALESCE(b.accounts_rece, b.note_accounts_rece) AS account_receivable, i.total_revenue, b.goodwill, "
                "b.total_equity AS total_holders_equity, "
                "b.monetaryfunds AS currency_funds, b.short_loan AS st_loan, "
                "b.long_loan AS lt_loan, b.bond_payable, "
                "b.noncurrent_liab_1year AS noncurrent_liab_in_1y, "
                "COALESCE(b.trade_finasset, 0) + COALESCE(b.fvtpl_finasset, 0) AS tradable_fin_assets "
                "FROM stock_indicators i "
                "JOIN stock_balance b ON i.code = b.code AND i.report_date = b.report_date "
                "WHERE i.code = ? AND i.report_type = 'annual' "
                "ORDER BY i.report_date DESC LIMIT ?",
                (code, years),
            )
            rows = await cursor.fetchall()
            fh_items = []
            for r in reversed(rows):
                int_debt = (
                    (r["st_loan"] or 0) + (r["lt_loan"] or 0) + (r["bond_payable"] or 0)
                    + (r["noncurrent_liab_in_1y"] or 0) + (r["tradable_fin_assets"] or 0)
                )
                fh_items.append({
                    "date": r["report_date"],
                    "debt_ratio": r["debt_ratio"],
                    "equity_multiplier": r["equity_multiplier"],
                    "equity_ratio": r["equity_ratio"],
                    "current_ratio": r["current_ratio"],
                    "quick_ratio": r["quick_ratio"],
                    "ar_revenue_ratio": round(r["account_receivable"] / r["total_revenue"] * 100, 2)
                        if r["total_revenue"] and r["account_receivable"] else None,
                    "goodwill_equity_ratio": round(r["goodwill"] / r["total_holders_equity"] * 100, 2)
                        if r["total_holders_equity"] and r["goodwill"] else None,
                    "cash_debt_ratio": round(r["currency_funds"] / int_debt * 100, 2)
                        if int_debt and r["currency_funds"] else None,
                })
            sections["financial_health"] = {"table": fh_items}
        else:
            # 仅用 indicators 的偿债指标
            cursor = await db.execute(
                "SELECT report_date, debt_ratio, equity_multiplier, equity_ratio, current_ratio, quick_ratio "
                "FROM stock_indicators WHERE code = ? AND report_type = 'annual' ORDER BY report_date DESC LIMIT ?",
                (code, years),
            )
            rows = await cursor.fetchall()
            fh_items = []
            for r in reversed(rows):
                fh_items.append({
                    "date": r["report_date"],
                    "debt_ratio": r["debt_ratio"],
                    "equity_multiplier": r["equity_multiplier"],
                    "equity_ratio": r["equity_ratio"],
                    "current_ratio": r["current_ratio"],
                    "quick_ratio": r["quick_ratio"],
                })
            sections["financial_health"] = {"table": fh_items}

        # ── 9. 排雷（需要 balance 表） ──
        if has_balance:
            # 货币资金
            cursor = await db.execute(
                "SELECT b.report_date, b.monetaryfunds AS currency_funds, b.total_assets, "
                "b.total_liabilities AS total_liab, i.total_revenue "
                "FROM stock_balance b "
                "JOIN stock_indicators i ON b.code = i.code AND b.report_date = i.report_date "
                "WHERE b.code = ? AND i.report_type = 'annual' ORDER BY b.report_date DESC LIMIT 5",
                (code,),
            )
            rows = await cursor.fetchall()
            currency_items = []
            for r in rows:
                currency_items.append({
                    "date": r["report_date"],
                    "currency_funds": _div100m(r["currency_funds"]),
                    "cf_assets_ratio": round(r["currency_funds"] / r["total_assets"] * 100, 2)
                        if r["total_assets"] and r["currency_funds"] else None,
                    "debt_ratio": round(r["total_liab"] / r["total_assets"] * 100, 2)
                        if r["total_assets"] and r["total_liab"] else None,
                    "cf_revenue_ratio": round(r["currency_funds"] / r["total_revenue"] * 100, 2)
                        if r["total_revenue"] and r["currency_funds"] else None,
                })

            # 应收
            cursor = await db.execute(
                "SELECT b.report_date, COALESCE(b.accounts_rece, b.note_accounts_rece) AS account_receivable, "
                "b.note_rece AS bills_receivable, b.note_payable AS bills_payable, "
                "COALESCE(b.other_rece, b.total_other_rece) AS other_receivables, b.total_assets, "
                "i.ar_turnover_days, i.total_revenue "
                "FROM stock_balance b "
                "JOIN stock_indicators i ON b.code = i.code AND b.report_date = i.report_date "
                "WHERE b.code = ? AND i.report_type = 'annual' ORDER BY b.report_date DESC LIMIT 5",
                (code,),
            )
            rows = await cursor.fetchall()
            ar_items = []
            for r in rows:
                rev = r["total_revenue"]
                ta = r["total_assets"]
                ar_items.append({
                    "date": r["report_date"],
                    "ar_revenue_ratio": round(r["account_receivable"] / rev * 100, 2)
                        if rev and r["account_receivable"] else None,
                    "bills_receivable_revenue_ratio": round(r["bills_receivable"] / rev * 100, 2)
                        if rev and r["bills_receivable"] else None,
                    "bills_receivable": _div100m(r["bills_receivable"]),
                    "bills_payable": _div100m(r["bills_payable"]),
                    "ar_turnover_days": r["ar_turnover_days"],
                    "other_receivables_assets_ratio": round(r["other_receivables"] / ta * 100, 2)
                        if ta and r["other_receivables"] else None,
                })

            # 存货及其他
            cursor = await db.execute(
                "SELECT b.report_date, b.inventory, b.cip AS construction_in_process, "
                "COALESCE(b.trade_finasset, 0) + COALESCE(b.fvtpl_finasset, 0) AS tradable_fin_assets, "
                "b.total_assets, i.fixed_asset_turnover, i.inventory_turnover_days "
                "FROM stock_balance b "
                "JOIN stock_indicators i ON b.code = i.code AND b.report_date = i.report_date "
                "WHERE b.code = ? AND i.report_type = 'annual' ORDER BY b.report_date DESC LIMIT 5",
                (code,),
            )
            rows = await cursor.fetchall()
            other_items = []
            for r in rows:
                ta = r["total_assets"]
                other_items.append({
                    "date": r["report_date"],
                    "inventory_assets_ratio": round(r["inventory"] / ta * 100, 2)
                        if ta and r["inventory"] else None,
                    "construction_assets_ratio": round(r["construction_in_process"] / ta * 100, 2)
                        if ta and r["construction_in_process"] else None,
                    "tradable_fin_assets_ratio": round(r["tradable_fin_assets"] / ta * 100, 2)
                        if ta and r["tradable_fin_assets"] else None,
                    "fixed_asset_turnover": r["fixed_asset_turnover"],
                    "inventory_turnover_days": r["inventory_turnover_days"],
                })

            sections["warnings"] = {
                "currency_funds": {"table": currency_items},
                "receivables": {"table": ar_items},
                "other_assets": {"table": other_items},
            }

    return sections


def _div100m(v):
    if v is None:
        return None
    return round(v / 1e8, 2)