"""个股看板 API（七步法）—— 搜索、数据查询、同步状态"""

import asyncio

from fastapi import APIRouter, Query

from ..db import get_db
from ..services.stock_data import (
    get_stock_sync_status,
    sync_stock_data,
    _needs_update,
)

router = APIRouter(prefix="/api", tags=["stock-dashboard"])


# ── 股票搜索（与旧版共用） ──────────────────────────────────


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


# ── 看板数据 ──────────────────────────────────────────────


@router.get("/stock-dashboard/{code}")
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


@router.get("/stock-dashboard/{code}/status")
async def get_dashboard_status(code: str):
    status = get_stock_sync_status(code)
    return {"code": code, **status}


# ── 工具函数 ──────────────────────────────────────────────


def _div100m(v):
    if v is None:
        return None
    return round(v / 1e8, 2)


def _safe_div(a, b, pct=False):
    if a is None or b is None or b == 0:
        return None
    r = a / b
    return round(r * 100, 2) if pct else round(r, 4)


def _year_label(report_date: str) -> str:
    return report_date[:4] if report_date else ""


def _cagr(values: list, n: int):
    """最近 n 个有效值的复合增速（%）"""
    valid = [v for v in values if v is not None and v > 0]
    if len(valid) < n + 1:
        return None
    start = valid[-(n + 1)]
    end = valid[-1]
    if start <= 0:
        return None
    return round((pow(end / start, 1 / n) - 1) * 100, 2)


def _interest_bearing_debt(row) -> float:
    return (
        (row["st_loan"] or 0)
        + (row["lt_loan"] or 0)
        + (row["bond_payable"] or 0)
        + (row["lease_liab"] or 0)
        + (row["noncurrent_liab_in_1y"] or 0)
    )


def _financial_assets(row) -> float:
    return (
        (row["monetaryfunds"] or 0)
        + (row["trade_finasset"] or 0)
        + (row["fvtpl_finasset"] or 0)
        + (row["available_sale_finasset"] or 0)
        + (row["hold_maturity_invest"] or 0)
        + (row["creditor_invest"] or 0)
    )


def _fixed_assets(row) -> float:
    return (
        (row["fixed_asset"] or 0)
        + (row["cip"] or 0)
        + (row["project_material"] or 0)
        + (row["fixed_asset_disposal"] or 0)
    )


def _long_operating_assets(row) -> float:
    return (
        _fixed_assets(row)
        + (row["intangible_asset"] or 0)
        + (row["develop_expense"] or 0)
        + (row["useright_asset"] or 0)
        + (row["goodwill"] or 0)
        + (row["long_prepaid_expense"] or 0)
    )


def _wc_narrow(row) -> float:
    ar = (row["accounts_rece"] or 0) + (row["note_accounts_rece"] or 0)
    ap = row["accounts_payable"] or 0
    pre_recv = (row["advance_receivables"] or 0) + (row["contract_liab"] or 0)
    return (
        ar
        + (row["prepayment"] or 0)
        + (row["inventory"] or 0)
        + (row["contract_asset"] or 0)
        - ap
        - pre_recv
    )


async def _has_table(db, table: str) -> bool:
    cursor = await db.execute(f"SELECT COUNT(*) FROM {table} LIMIT 1")
    row = await cursor.fetchone()
    return row[0] > 0


async def _fetch_annual_rows(db, code: str, years: int):
    """拉取年报指标 + 三大表关联行（时间升序）"""
    has_balance = await _has_table(db, "stock_balance")
    has_income = await _has_table(db, "stock_income")
    has_cashflow = await _has_table(db, "stock_cashflow")

    if has_balance and has_income and has_cashflow:
        cursor = await db.execute(
            """
            SELECT i.*,
                   COALESCE(inc.parent_netprofit, inc.netprofit) AS inc_net_profit,
                   inc.deduct_parent_netprofit,
                   inc.operate_income, inc.operate_cost,
                   inc.sale_expense, inc.manage_expense, inc.research_expense, inc.finance_expense,
                   COALESCE(inc.fairvalue_change_income, 0) AS fairvalue_change_income,
                   COALESCE(inc.invest_income, 0) AS invest_income,
                   COALESCE(inc.operate_profit, 0) AS operate_profit_raw,
                   cf.netcash_operate, cf.construct_long_asset,
                   COALESCE(cf.fa_ir_depr, 0) AS depreciation,
                   b.total_assets, b.total_current_assets, b.total_noncurrent_assets,
                   b.total_liabilities, b.total_parent_equity,
                   b.monetaryfunds, b.accounts_rece, b.note_accounts_rece,
                   b.prepayment, b.inventory, b.contract_asset,
                   b.accounts_payable, b.advance_receivables, b.contract_liab,
                   b.short_loan AS st_loan, b.long_loan AS lt_loan,
                   b.bond_payable, b.lease_liab, b.noncurrent_liab_1year AS noncurrent_liab_in_1y,
                   b.trade_finasset, b.fvtpl_finasset, b.available_sale_finasset,
                   b.hold_maturity_invest, b.creditor_invest,
                   b.fixed_asset, b.cip, b.project_material, b.fixed_asset_disposal,
                   b.intangible_asset, b.develop_expense, b.useright_asset,
                   b.goodwill, b.long_prepaid_expense,
                   b.other_current_asset
            FROM stock_indicators i
            LEFT JOIN stock_income inc ON i.code = inc.code AND i.report_date = inc.report_date
            LEFT JOIN stock_cashflow cf ON i.code = cf.code AND i.report_date = cf.report_date
            LEFT JOIN stock_balance b ON i.code = b.code AND i.report_date = b.report_date
            WHERE i.code = ? AND i.report_type = 'annual'
            ORDER BY i.report_date DESC LIMIT ?
            """,
            (code, years),
        )
    elif has_balance:
        cursor = await db.execute(
            """
            SELECT i.*, NULL AS inc_net_profit, NULL AS deduct_parent_netprofit,
                   NULL AS operate_income, NULL AS operate_cost,
                   NULL AS sale_expense, NULL AS manage_expense, NULL AS research_expense, NULL AS finance_expense,
                   0 AS fairvalue_change_income, 0 AS invest_income, 0 AS operate_profit_raw,
                   NULL AS netcash_operate, NULL AS construct_long_asset, 0 AS depreciation,
                   b.total_assets, b.total_current_assets, b.total_noncurrent_assets,
                   b.total_liabilities, b.total_parent_equity,
                   b.monetaryfunds, b.accounts_rece, b.note_accounts_rece,
                   b.prepayment, b.inventory, b.contract_asset,
                   b.accounts_payable, b.advance_receivables, b.contract_liab,
                   b.short_loan AS st_loan, b.long_loan AS lt_loan,
                   b.bond_payable, b.lease_liab, b.noncurrent_liab_1year AS noncurrent_liab_in_1y,
                   b.trade_finasset, b.fvtpl_finasset, b.available_sale_finasset,
                   b.hold_maturity_invest, b.creditor_invest,
                   b.fixed_asset, b.cip, b.project_material, b.fixed_asset_disposal,
                   b.intangible_asset, b.develop_expense, b.useright_asset,
                   b.goodwill, b.long_prepaid_expense,
                   b.other_current_asset
            FROM stock_indicators i
            LEFT JOIN stock_balance b ON i.code = b.code AND i.report_date = b.report_date
            WHERE i.code = ? AND i.report_type = 'annual'
            ORDER BY i.report_date DESC LIMIT ?
            """,
            (code, years),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM stock_indicators WHERE code = ? AND report_type = 'annual' "
            "ORDER BY report_date DESC LIMIT ?",
            (code, years),
        )

    rows = await cursor.fetchall()
    return list(reversed([dict(r) for r in rows]))


# ── 看板数据组装 ─────────────────────────────────────────────


async def _build_dashboard(code: str, years: int) -> dict:
    sections = {}

    async with get_db() as db:
        rows = await _fetch_annual_rows(db, code, years)
        if not rows:
            return sections

        dates = [r["report_date"] for r in rows]
        year_labels = [_year_label(d) for d in dates]
        latest = rows[-1]

        # ── 快照 ──
        fcf_latest = None
        if latest.get("netcash_operate") is not None:
            capex = latest.get("construct_long_asset") or 0
            fcf_latest = _div100m((latest["netcash_operate"] or 0) - capex)

        sections["snapshot"] = {
            "report_date": latest["report_date"],
            "revenue": _div100m(latest.get("total_revenue")),
            "net_profit": _div100m(latest.get("net_profit")),
            "net_margin": latest.get("net_margin"),
            "gross_margin": latest.get("gross_margin"),
            "roe": latest.get("roe_diluted") or latest.get("roe"),
            "cfnp": latest.get("cfnp"),
            "fcf": fcf_latest,
            "fcf_positive": fcf_latest is not None and fcf_latest > 0,
        }

        # ── 第一步：营收与盈利质量 ──
        basic = {
            "revenue": [], "revenue_yoy": [], "net_profit": [],
            "operating_profit": [], "financial_profit": [], "net_profit_yoy": [],
            "net_margin": [], "net_profit_adjusted": [], "operating_cf": [],
            "fcf": [], "gross_profit": [], "gross_margin": [],
        }
        quality = {
            "deduct_ratio": [], "operating_ratio": [], "cfnp": [],
            "fcf_sign": [], "minority_gap": [],
        }

        for r in rows:
            rev = r.get("total_revenue")
            np = r.get("net_profit")
            fin_profit = (r.get("fairvalue_change_income") or 0) + (r.get("invest_income") or 0)
            op_profit = None
            if np is not None:
                op_profit = _div100m(np - fin_profit)
            elif r.get("operate_profit_raw"):
                op_profit = _div100m(r["operate_profit_raw"])

            gross_profit = None
            if rev and r.get("operate_cost") is not None:
                gross_profit = _div100m(rev - r["operate_cost"])
            elif rev and r.get("gross_margin") is not None:
                gross_profit = _div100m(rev * r["gross_margin"] / 100)

            fcf = None
            if r.get("netcash_operate") is not None:
                fcf = _div100m((r["netcash_operate"] or 0) - (r.get("construct_long_asset") or 0))

            basic["revenue"].append(_div100m(rev))
            basic["revenue_yoy"].append(r.get("revenue_yoy"))
            basic["net_profit"].append(_div100m(np))
            basic["operating_profit"].append(op_profit)
            basic["financial_profit"].append(_div100m(fin_profit) if fin_profit else None)
            basic["net_profit_yoy"].append(r.get("net_profit_yoy"))
            basic["net_margin"].append(r.get("net_margin"))
            basic["net_profit_adjusted"].append(_div100m(r.get("net_profit_adjusted")))
            basic["operating_cf"].append(_div100m(r.get("netcash_operate")))
            basic["fcf"].append(fcf)
            basic["gross_profit"].append(gross_profit)
            basic["gross_margin"].append(r.get("gross_margin"))

            deduct = r.get("net_profit_adjusted")
            quality["deduct_ratio"].append(
                round(deduct / np, 2) if deduct and np else None
            )
            quality["operating_ratio"].append(
                round(op_profit / _div100m(np), 2) if op_profit and np and _div100m(np) else None
            )
            quality["cfnp"].append(r.get("cfnp"))
            quality["fcf_sign"].append(
                "正" if fcf is not None and fcf > 0 else ("负" if fcf is not None else None)
            )
            inc_np = r.get("inc_net_profit")
            quality["minority_gap"].append(
                "≈" if inc_np is None or np is None or abs(inc_np - np) / max(abs(np), 1) < 0.05 else "≠"
            )

        sections["step1"] = {
            "years": year_labels,
            "dates": dates,
            "basic": basic,
            "quality": quality,
        }

        # ── 第二步：成本费用构成 ──
        gm = latest.get("gross_margin")
        nm = latest.get("net_margin")
        rev_latest = latest.get("total_revenue") or latest.get("operate_income")
        expense_chart = {
            "dates": year_labels,
            "gross_margin": [r.get("gross_margin") for r in rows],
            "net_margin": [r.get("net_margin") for r in rows],
            "rd_rate": [], "sales_rate": [], "admin_rate": [], "finance_rate": [],
        }
        for r in rows:
            rev = r.get("operate_income") or r.get("total_revenue")
            expense_chart["rd_rate"].append(_safe_div(r.get("research_expense"), rev, pct=True))
            expense_chart["sales_rate"].append(_safe_div(r.get("sale_expense"), rev, pct=True))
            expense_chart["admin_rate"].append(_safe_div(r.get("manage_expense"), rev, pct=True))
            expense_chart["finance_rate"].append(_safe_div(r.get("finance_expense"), rev, pct=True))

        sections["step2"] = {
            "latest": {
                "margin_gap": round(gm - nm, 2) if gm is not None and nm is not None else None,
                "rd_rate": expense_chart["rd_rate"][-1],
                "sales_rate": expense_chart["sales_rate"][-1],
                "admin_rate": expense_chart["admin_rate"][-1],
                "finance_rate": expense_chart["finance_rate"][-1],
            },
            "chart": expense_chart,
        }

        # ── 第三步：成长性 ──
        rev_vals = basic["revenue"]
        np_vals = basic["net_profit"]
        sections["step3"] = {
            "latest": {
                "revenue_yoy": latest.get("revenue_yoy"),
                "profit_yoy": latest.get("net_profit_yoy"),
                "revenue_cagr3": _cagr(rev_vals, 3),
                "profit_cagr3": _cagr(np_vals, 3),
                "revenue_cagr5": _cagr(rev_vals, 5),
                "profit_cagr5": _cagr(np_vals, 5),
            },
            "chart": {
                "dates": year_labels,
                "revenue_yoy": basic["revenue_yoy"],
                "profit_yoy": basic["net_profit_yoy"],
            },
        }

        # ── 第四步：业务构成（暂无分业务数据源） ──
        sections["step4"] = {
            "available": False,
            "message": "分业务营收/毛利数据需从年报附注解析，当前数据源暂不支持",
        }

        # ── 第五步：资产负债 ──
        if latest.get("total_assets"):
            ta = latest["total_assets"]
            ca = latest.get("total_current_assets") or 0
            nca = latest.get("total_noncurrent_assets") or (ta - ca)
            int_debt = _interest_bearing_debt(latest)
            ap = latest.get("accounts_payable") or 0
            pre_recv = (latest.get("advance_receivables") or 0) + (latest.get("contract_liab") or 0)
            non_int_debt = ap + pre_recv
            fin_assets = _financial_assets(latest)
            op_assets = ta - fin_assets
            op_liab = (latest.get("total_liabilities") or 0) - int_debt
            noa = op_assets - op_liab
            nfa = fin_assets - int_debt
            op_profit_latest = basic["operating_profit"][-1]
            noa_return = None
            if op_profit_latest and noa:
                noa_return = round(op_profit_latest / _div100m(noa) * 100, 2) if _div100m(noa) else None

            balance_rows = []
            for r in rows:
                if not r.get("total_assets"):
                    continue
                r_ta = r["total_assets"]
                r_int = _interest_bearing_debt(r)
                r_ap = r.get("accounts_payable") or 0
                r_pre = (r.get("advance_receivables") or 0) + (r.get("contract_liab") or 0)
                balance_rows.append({
                    "year": _year_label(r["report_date"]),
                    "currency_funds": _div100m(r.get("monetaryfunds")),
                    "inventory": _div100m(r.get("inventory")),
                    "other_current": _div100m(r.get("other_current_asset")),
                    "current_assets": _div100m(r.get("total_current_assets")),
                    "noncurrent_assets": _div100m(r.get("total_noncurrent_assets")),
                    "total_assets": _div100m(r_ta),
                    "interest_debt": _div100m(r_int),
                    "accounts_payable": _div100m(r_ap),
                    "advance_receivables": _div100m(r.get("advance_receivables")),
                    "contract_liab": _div100m(r.get("contract_liab")),
                    "non_interest_debt": _div100m(r_ap + r_pre),
                    "total_liab": _div100m(r.get("total_liabilities")),
                    "debt_ratio": r.get("debt_ratio"),
                    "parent_equity": _div100m(r.get("total_parent_equity")),
                })

            sections["step5"] = {
                "latest": {
                    "total_assets": _div100m(ta),
                    "current_assets": _div100m(ca),
                    "noncurrent_assets": _div100m(nca),
                    "current_pct": _safe_div(ca, ta, pct=True),
                    "noncurrent_pct": _safe_div(nca, ta, pct=True),
                    "debt_ratio": latest.get("debt_ratio"),
                    "interest_debt": _div100m(int_debt),
                    "non_interest_debt": _div100m(non_int_debt),
                    "interest_pct": _safe_div(int_debt, int_debt + non_int_debt, pct=True),
                    "non_interest_pct": _safe_div(non_int_debt, int_debt + non_int_debt, pct=True),
                    "noa": _div100m(noa),
                    "nfa": _div100m(nfa),
                    "noa_return": noa_return,
                },
                "table": balance_rows,
            }

        # ── 第六步：投入产出 ──
        wc_rows = []
        fa_rows = []
        wc_chart = {"dates": [], "wc_per_revenue": []}
        fa_chart = {"dates": [], "fa_per_revenue": [], "lt_per_revenue": []}

        prev_wc = None
        for r in rows:
            rev = r.get("total_revenue") or r.get("operate_income")
            if not rev or not r.get("total_assets"):
                continue
            yr = _year_label(r["report_date"])
            wc = _wc_narrow(r)
            fa = _fixed_assets(r)
            lt = _long_operating_assets(r)
            wc_per = round(wc / rev, 4) if rev else None
            fa_per = round(fa / rev, 4) if rev else None
            lt_per = round(lt / rev, 4) if rev else None

            wc_chart["dates"].append(yr)
            wc_chart["wc_per_revenue"].append(wc_per)
            fa_chart["dates"].append(yr)
            fa_chart["fa_per_revenue"].append(fa_per)
            fa_chart["lt_per_revenue"].append(lt_per)

            ar = (r.get("accounts_rece") or 0) + (r.get("note_accounts_rece") or 0)
            ap = r.get("accounts_payable") or 0
            pre_recv = (r.get("advance_receivables") or 0) + (r.get("contract_liab") or 0)
            wc_delta = round(_div100m(wc - prev_wc), 2) if prev_wc is not None else None
            prev_wc = wc

            wc_rows.append({
                "year": yr,
                "wc_per_revenue": wc_per,
                "wc": _div100m(wc),
                "ar": _div100m(ar),
                "prepayment": _div100m(r.get("prepayment")),
                "inventory": _div100m(r.get("inventory")),
                "accounts_payable": _div100m(ap),
                "advance_receivables": _div100m(r.get("advance_receivables")),
                "contract_liab": _div100m(r.get("contract_liab")),
                "ar_ratio": _safe_div(ar, rev, pct=True),
                "prepay_ratio": _safe_div(r.get("prepayment"), rev, pct=True),
                "inventory_ratio": _safe_div(r.get("inventory"), rev, pct=True),
                "ap_ratio": _safe_div(ap, rev, pct=True),
                "advance_ratio": _safe_div(r.get("advance_receivables"), rev, pct=True),
                "contract_ratio": _safe_div(r.get("contract_liab"), rev, pct=True),
                "wc_delta": wc_delta,
            })

            depr = r.get("depreciation") or 0
            fa_rows.append({
                "year": yr,
                "fa_per_revenue": fa_per,
                "lt_per_revenue": lt_per,
                "fixed_assets": _div100m(fa),
                "long_operating_assets": _div100m(lt),
                "depreciation": _div100m(depr),
                "depr_ratio": _safe_div(depr, rev, pct=True),
            })

        sections["step6"] = {
            "wc_chart": wc_chart,
            "wc_table": wc_rows,
            "fa_chart": fa_chart,
            "fa_table": fa_rows,
            "human": {"available": False, "message": "人员结构数据需从年报解析，当前暂不支持"},
        }

        # ── 第七步：收益率 ──
        dupont = []
        roe_chart = {"dates": [], "roe": [], "roa": [], "roic": []}
        for r in rows:
            rev = r.get("total_revenue")
            np = r.get("net_profit")
            ta = r.get("total_assets")
            npr = _safe_div(np, rev, pct=True)
            turnover = r.get("total_asset_turnover")
            leverage = r.get("equity_multiplier")
            roe = r.get("roe_diluted") or r.get("roe")
            roa = r.get("roa")

            int_debt = _interest_bearing_debt(r) if r.get("total_assets") else 0
            equity = r.get("total_parent_equity") or 0
            invested = equity + int_debt - (r.get("monetaryfunds") or 0)
            fin_profit = (r.get("fairvalue_change_income") or 0) + (r.get("invest_income") or 0)
            nopat = None
            if np is not None:
                nopat = (np - fin_profit) * 0.75
            roic = _safe_div(nopat, invested, pct=True) if invested and invested > 0 else None

            yr = _year_label(r["report_date"])
            dupont.append({
                "year": yr,
                "net_profit_rate": npr,
                "turnover": turnover,
                "leverage": leverage,
                "roe": roe,
            })
            roe_chart["dates"].append(yr)
            roe_chart["roe"].append(roe)
            roe_chart["roa"].append(roa)
            roe_chart["roic"].append(roic)

        sections["step7"] = {
            "latest": {
                "roe": latest.get("roe_diluted") or latest.get("roe"),
                "roa": latest.get("roa"),
                "roic": roe_chart["roic"][-1] if roe_chart["roic"] else None,
                "net_profit_rate": dupont[-1]["net_profit_rate"] if dupont else None,
                "turnover": latest.get("total_asset_turnover"),
                "leverage": latest.get("equity_multiplier"),
            },
            "dupont_table": dupont,
            "chart": roe_chart,
        }

    return sections
