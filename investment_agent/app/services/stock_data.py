"""个股数据同步服务 —— 从 AKShare 拉取数据存入 SQLite，按需增量更新。

数据源（仅使用当前网络环境可达的）：
- stock_financial_analysis_indicator: 86项财务指标（比率为主，含部分绝对值）
- stock_profile_cninfo: 公司基本信息（名称、行业、上市日期）
- stock_info_a_code_name: 代码→名称映射（搜索用）
- stock_financial_report_sina / stock_individual_info_em: 不可达（网络限制）→ 对应表格数据为空
"""

import asyncio
import logging
from datetime import datetime, timezone, time
from typing import Any

from ..db import get_db

logger = logging.getLogger(__name__)

_sync_status: dict[str, dict] = {}
TRADING_START = time(9, 30)
TRADING_END = time(15, 0)


def _is_trading_time() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return TRADING_START <= now.time() <= TRADING_END


async def _needs_update(code: str) -> bool:
    """需要更新？交易时段超1h / 非交易时段超1天"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT updated_at FROM stock_info WHERE code = ?", (code,)
        )
        row = await cursor.fetchone()
        if not row or not row["updated_at"]:
            return True
        updated_at = datetime.fromisoformat(row["updated_at"])
        now = datetime.now(timezone.utc)
        delta = now - updated_at.replace(tzinfo=timezone.utc)
        threshold = 3600 if _is_trading_time() else 86400
        return delta.total_seconds() > threshold


def _parse_float(v: Any) -> float | None:
    import math
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _pick(row, columns: dict[str, str]) -> dict:
    result = {}
    for target, src in columns.items():
        val = row.get(src)
        if val is not None:
            result[target] = _parse_float(val)
    return result


# ── 数据抓取 ──────────────────────────────────────────────


async def _fetch_info(code: str) -> dict | None:
    """获取股票基本信息（巨潮资讯 + A股代码表）"""
    import akshare as ak

    loop = asyncio.get_event_loop()

    name = code
    industry = ""
    listed_date = ""

    # 巨潮资讯
    try:
        df = await loop.run_in_executor(None, ak.stock_profile_cninfo, code)
        if len(df) > 0:
            row = df.iloc[0]
            name = str(row.get("A股简称", code))
            industry = str(row.get("所属行业", ""))
            listed_date = str(row.get("上市日期", ""))
    except Exception as e:
        logger.warning(f"[stock_data] stock_profile_cninfo failed: {e}")

    # 代码名称表（fallback）
    if name == code:
        try:
            df_names = await loop.run_in_executor(None, ak.stock_info_a_code_name)
            match = df_names[df_names["code"] == code]
            if len(match) > 0:
                name = str(match.iloc[0]["name"])
        except Exception as e:
            logger.warning(f"[stock_data] stock_info_a_code_name failed: {e}")

    return {
        "code": code,
        "name": name,
        "industry": industry,
        "market_cap": None,
        "listed_date": listed_date,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    } if name else None


async def _fetch_indicators(code: str) -> list[dict]:
    """AKShare stock_financial_analysis_indicator（86列，含比率+每股+绝对值）"""
    import akshare as ak

    loop = asyncio.get_event_loop()

    # 2015年起逐年后退尝试，兼容上市较晚（如京沪高铁2020上市）导致早期年份无数据
    df = None
    import datetime as _dt
    start_year = 2015
    end_year = _dt.datetime.now().year
    for year in range(start_year, end_year + 1):
        df = await loop.run_in_executor(
            None, ak.stock_financial_analysis_indicator, code, str(year)
        )
        if len(df) > 0:
            break

    # 所有年份均无数据
    if df is None or len(df) == 0:
        return []

    # 全部 86 列的映射（仅保留我们能用的）
    col_map = {
        # 盈利比率
        "gross_margin": "销售毛利率(%)",
        "net_margin": "销售净利率(%)",
        "roe": "净资产收益率(%)",
        "roe_diluted": "加权净资产收益率(%)",
        "roa": "总资产净利润率(%)",
        # 成长
        "revenue_yoy": "主营业务收入增长率(%)",
        "net_profit_yoy": "净利润增长率(%)",
        "equity_yoy": "净资产增长率(%)",
        "total_assets_yoy": "总资产增长率(%)",
        # 每股
        "eps": "摊薄每股收益(元)",
        "bvps": "每股净资产_调整前(元)",
        "cfps": "每股经营性现金流(元)",
        # 偿债
        "debt_ratio": "资产负债率(%)",
        "current_ratio": "流动比率",
        "quick_ratio": "速动比率",
        "equity_ratio": "产权比率(%)",
        # 营运
        "ar_turnover": "应收账款周转率(次)",
        "ar_turnover_days": "应收账款周转天数(天)",
        "inventory_turnover": "存货周转率(次)",
        "inventory_turnover_days": "存货周转天数(天)",
        "fixed_asset_turnover": "固定资产周转率(次)",
        "total_asset_turnover": "总资产周转率(次)",
        # 现金流
        "cfr": "经营现金净流量对销售收入比率(%)",
        "cfnp": "经营现金净流量与净利润的比率(%)",
        # 绝对值（亿元）
        "total_assets": "总资产(元)",
    }

    DE_RATIO_COL = "负债与所有者权益比率(%)"
    NPADJ_COL = "扣除非经常性损益后的净利润(元)"

    rows = []
    sorted_rows = df.sort_values("日期")

    prev_npadj = None
    for _, row in sorted_rows.iterrows():
        raw_date = row.get("日期")
        if raw_date is None:
            continue

        record = {"code": code, "report_date": str(raw_date)}

        # 报告类型
        try:
            dt = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d")
            month, day = dt.month, dt.day
            if month == 12 and day == 31:
                record["report_type"] = "annual"
            elif month == 3 and day == 31:
                record["report_type"] = "q1"
            elif month == 6 and day == 30:
                record["report_type"] = "half"
            elif month == 9 and day == 30:
                record["report_type"] = "q3"
        except (ValueError, TypeError):
            pass

        # 主映射
        record.update(_pick(row, col_map))

        # 权益乘数 = 1 + 负债与所有者权益比率 / 100
        de = _parse_float(row.get(DE_RATIO_COL))
        if de is not None:
            record["equity_multiplier"] = 1 + de / 100

        # 扣非净利润 + 同比
        npadj = _parse_float(row.get(NPADJ_COL))
        if npadj is not None:
            record["net_profit_adjusted"] = npadj
            if prev_npadj and prev_npadj != 0:
                record["net_profit_adjusted_yoy"] = (npadj - prev_npadj) / abs(prev_npadj) * 100

        # 营业收入、净利润绝对值（AKShare 未直接在 indicator 提供，从 THS 补充）
        # total_revenue/net_profit 由 sync 主流程用 THS 数据补充

        rows.append(record)
        prev_npadj = npadj

    return rows


async def _fetch_ths_abstract(code: str) -> list[dict]:
    """THS 财务摘要（利润表模式即可，三张表返回相同列）"""
    import akshare as ak

    loop = asyncio.get_event_loop()
    df = await loop.run_in_executor(
        None, ak.stock_financial_abstract_ths, code, "利润表"
    )

    rows = []
    for _, row in df.iterrows():
        rd = row.get("报告期")
        if rd is None:
            continue
        rec = {
            "code": code,
            "report_date": str(rd),
            "total_revenue": _parse_float(row.get("营业总收入")),
            "net_profit": _parse_float(row.get("净利润")),
        }
        rows.append(rec)
    return rows



# ── 东财三大报表 ──────────────────────────────────────────

# 东财 API 返回的 metadata 列（不存入 DB）
_EM_META_COLS = {
    "SECUCODE", "SECURITY_CODE", "SECURITY_NAME_ABBR", "ORG_CODE", "ORG_TYPE",
    "REPORT_DATE", "REPORT_TYPE", "REPORT_DATE_NAME", "SECURITY_TYPE_CODE",
    "NOTICE_DATE", "UPDATE_DATE", "CURRENCY", "OPINION_TYPE", "OSOPINION_TYPE",
    "LISTING_STATE",
}


def _code_to_em_symbol(code: str) -> str:
    """将纯数字代码转为东财格式：600519 → SH600519, 000001 → SZ000001"""
    if code.startswith("6"):
        return f"SH{code}"
    else:
        return f"SZ{code}"


def _parse_em_dataframe(df, code: str) -> list[dict]:
    """解析东财报表 DataFrame → list[dict]，列名转小写蛇形，过滤 metadata 和 _YOY"""
    # 确定数据列（排除 metadata 和 YOY，只做一次）
    data_cols = [c for c in df.columns if c not in _EM_META_COLS and not c.endswith("_YOY")]

    rows = []
    sorted_rows = df.sort_values("REPORT_DATE")

    for _, row in sorted_rows.iterrows():
        raw_date = row.get("REPORT_DATE")
        if raw_date is None:
            continue
        rd_str = str(raw_date)[:10]

        # 报告类型
        report_type = None
        raw_report_type = row.get("REPORT_TYPE")
        if raw_report_type:
            rt = str(raw_report_type)
            if "一季" in rt or "Q1" in rt.upper():
                report_type = "q1"
            elif "半年" in rt or "中报" in rt:
                report_type = "half"
            elif "三季" in rt or "Q3" in rt.upper():
                report_type = "q3"
            elif "年报" in rt or "年度" in rt:
                report_type = "annual"

        record: dict = {"code": code, "report_date": rd_str, "report_type": report_type}

        # 始终写入所有数据列，值为 None 也保留 key
        for col in data_cols:
            record[col.lower()] = _parse_float(row.get(col))

        rows.append(record)
    return rows


async def _fetch_balance_sheet_em(code: str) -> list[dict]:
    """东财资产负债表 — stock_balance_sheet_by_report_em（152 个数据列）"""
    import akshare as ak

    symbol = _code_to_em_symbol(code)
    loop = asyncio.get_event_loop()
    df = await loop.run_in_executor(None, ak.stock_balance_sheet_by_report_em, symbol)

    return _parse_em_dataframe(df, code)


async def _fetch_income_statement_em(code: str) -> list[dict]:
    """东财利润表 — stock_profit_sheet_by_report_em（95 个数据列）"""
    import akshare as ak

    symbol = _code_to_em_symbol(code)
    loop = asyncio.get_event_loop()
    df = await loop.run_in_executor(None, ak.stock_profit_sheet_by_report_em, symbol)

    return _parse_em_dataframe(df, code)


async def _fetch_cashflow_em(code: str) -> list[dict]:
    """东财现金流量表 — stock_cash_flow_sheet_by_report_em（120 个数据列）"""
    import akshare as ak

    symbol = _code_to_em_symbol(code)
    loop = asyncio.get_event_loop()
    df = await loop.run_in_executor(None, ak.stock_cash_flow_sheet_by_report_em, symbol)

    return _parse_em_dataframe(df, code)


# ── 状态管理 ──────────────────────────────────────────────


def _get_sync_status(code: str) -> dict:
    return _sync_status.get(code, {"status": "unknown"})


def _set_sync_status(code: str, status: str, progress: str = "", error: str = ""):
    _sync_status[code] = {"status": status, "progress": progress, "error": error}


def get_stock_sync_status(code: str) -> dict:
    return _get_sync_status(code)


# ── 主同步流程 ──────────────────────────────────────────────


async def sync_stock_data(code: str) -> None:
    """同步个股数据。

    可用数据源: stock_financial_analysis_indicator (86项指标)
    stock_profile_cninfo (基本信息，巨潮)
    stock_financial_abstract_ths (THS 摘要：营收、净利润绝对值)
    """
    existing = _get_sync_status(code)
    if existing["status"] == "syncing":
        return

    _set_sync_status(code, "syncing", "1/3 获取基本信息...")
    logger.info(f"[stock_data] 开始同步 {code}")

    errors = []

    try:

        # 步骤1: 基本信息
        info = await _fetch_info(code)
        if info is None:
            raise ValueError(f"无法获取 {code} 的基本信息")

        # 步骤2: 财务指标 + 三大报表（并行）
        _set_sync_status(code, "syncing", "2/3 获取财务数据...")
        ind_task = asyncio.create_task(_fetch_indicators(code))
        ths_task = asyncio.create_task(_fetch_ths_abstract(code))
        balance_task = asyncio.create_task(_fetch_balance_sheet_em(code))
        income_task = asyncio.create_task(_fetch_income_statement_em(code))
        cashflow_task = asyncio.create_task(_fetch_cashflow_em(code))

        indicators = await ind_task
        ths_data = await ths_task
        balance_data = await balance_task
        income_data = await income_task
        cashflow_data = await cashflow_task
        logger.info(
            f"[stock_data] indicators={len(indicators)}, ths={len(ths_data)}, "
            f"balance={len(balance_data)}, income={len(income_data)}, "
            f"cashflow={len(cashflow_data)}"
        )

        # 用东财利润表补充 total_revenue / net_profit（优先），THS 作为 fallback
        income_by_date = {inc["report_date"]: inc for inc in income_data}
        ths_by_date = {t["report_date"]: t for t in ths_data}
        for ind in indicators:
            inc = income_by_date.get(ind["report_date"])
            if inc and inc.get("operate_income"):
                ind["total_revenue"] = inc["operate_income"]
            if inc and inc.get("parent_netprofit"):
                ind["net_profit"] = inc["parent_netprofit"]
            elif inc and inc.get("netprofit"):
                ind["net_profit"] = inc["netprofit"]
            # THS fallback（如果东财数据缺失）
            if not ind.get("total_revenue") or not ind.get("net_profit"):
                ths = ths_by_date.get(ind["report_date"])
                if ths:
                    ind["total_revenue"] = ind.get("total_revenue") or ths.get("total_revenue")
                    ind["net_profit"] = ind.get("net_profit") or ths.get("net_profit")
            # 用东财利润表计算 gross_margin（AKShare 近期数据为 NaN）
            inc = income_by_date.get(ind["report_date"])
            if inc and inc.get("operate_income") and inc.get("operate_cost") and inc["operate_income"] != 0:
                if ind.get("gross_margin") is None:
                    ind["gross_margin"] = round(
                        (inc["operate_income"] - inc["operate_cost"]) / inc["operate_income"] * 100, 2
                    )

        # 步骤3: 写入数据库
        _set_sync_status(code, "syncing", "3/3 写入数据库...")

        async with get_db() as db:

            # stock_info
            await db.execute(
                """INSERT INTO stock_info (code, name, industry, market_cap, listed_date, updated_at)
                   VALUES (:code, :name, :industry, :market_cap, :listed_date, :updated_at)
                   ON CONFLICT(code) DO UPDATE SET
                       name=:name, industry=:industry, market_cap=:market_cap,
                       listed_date=:listed_date, updated_at=:updated_at""",
                info,
            )

            # stock_indicators
            indicator_fields = [
                "code", "report_date", "report_type", "total_revenue", "net_profit",
                "net_profit_adjusted", "gross_margin", "net_margin", "roe",
                "roe_diluted", "roa", "revenue_yoy", "net_profit_yoy",
                "net_profit_adjusted_yoy", "equity_yoy", "total_assets_yoy",
                "eps", "bvps", "cfps", "debt_ratio", "current_ratio",
                "quick_ratio", "equity_multiplier", "equity_ratio",
                "ar_turnover", "ar_turnover_days", "inventory_turnover",
                "inventory_turnover_days", "fixed_asset_turnover",
                "total_asset_turnover", "cfr", "cfnp",
            ]
            for row in indicators:
                params = {k: row.get(k) for k in indicator_fields}
                set_clause = ", ".join(f"{k}=:{k}" for k in indicator_fields if k not in ("code", "report_date"))
                await db.execute(
                    f"""INSERT INTO stock_indicators ({", ".join(indicator_fields)})
                        VALUES ({", ".join(':' + f for f in indicator_fields)})
                        ON CONFLICT(code, report_date) DO UPDATE SET {set_clause}""",
                    params,
                )

            # 三大报表：东财数据，动态列写入（支持不同公司类型字段差异）
            for table_name, data in [
                ("stock_balance", balance_data),
                ("stock_income", income_data),
                ("stock_cashflow", cashflow_data),
            ]:
                if not data:
                    continue
                all_fields = list(data[0].keys())

                # 检查并添加表中不存在的列（通过 ALTER TABLE）
                cursor = await db.execute(f"PRAGMA table_info({table_name})")
                existing_cols = {row[1] for row in await cursor.fetchall()}
                for col in all_fields:
                    if col not in existing_cols:
                        await db.execute(
                            f"ALTER TABLE {table_name} ADD COLUMN {col} REAL"
                        )
                        logger.info(f"[stock_data] ALTER TABLE {table_name} ADD COLUMN {col}")

                # DML 写入
                for row in data:
                    params = {k: row.get(k) for k in all_fields}
                    set_clause = ", ".join(
                        f"{k}=:{k}" for k in all_fields if k not in ("code", "report_date")
                    )
                    await db.execute(
                        f"""INSERT INTO {table_name} ({", ".join(all_fields)})
                            VALUES ({", ".join(':' + f for f in all_fields)})
                            ON CONFLICT(code, report_date) DO UPDATE SET {set_clause}""",
                        params,
                    )

            await db.commit()

            # Backfill: 用 stock_income 更新已有 indicators 行中 total_revenue/net_profit 为 NULL 的
            await db.execute(
                """UPDATE stock_indicators SET
                    total_revenue = (SELECT operate_income FROM stock_income
                        WHERE stock_income.code = stock_indicators.code
                        AND stock_income.report_date = stock_indicators.report_date),
                    net_profit = (SELECT parent_netprofit FROM stock_income
                        WHERE stock_income.code = stock_indicators.code
                        AND stock_income.report_date = stock_indicators.report_date),
                WHERE code = ? AND total_revenue IS NULL""",
                (code,),
            )
            # Backfill: 用 stock_income 计算并更新 gross_margin（AKShare 近期数据为 NaN）
            await db.execute(
                """UPDATE stock_indicators SET gross_margin = (
                    SELECT ROUND((operate_income - operate_cost) / operate_income * 100, 2)
                    FROM stock_income
                    WHERE stock_income.code = stock_indicators.code
                    AND stock_income.report_date = stock_indicators.report_date
                    AND operate_income IS NOT NULL AND operate_income != 0
                )
                WHERE code = ? AND gross_margin IS NULL""",
                (code,),
            )
            await db.commit()

        _set_sync_status(code, "ready", "同步完成")
        logger.info(
            f"[stock_data] 同步完成 {code}: indicators={len(indicators)}, "
            f"balance={len(balance_data)}, income={len(income_data)}, "
            f"cashflow={len(cashflow_data)}"
        )

    except Exception as e:
        _set_sync_status(code, "error", "", str(e))
        logger.error(f"[stock_data] 同步失败 {code}: {e}")
        raise


async def check_and_sync(code: str) -> dict:
    needs = await _needs_update(code)
    if needs:
        existing = _get_sync_status(code)
        if existing["status"] != "syncing":
            asyncio.create_task(sync_stock_data(code))
        return {"needs_update": True, "status": "updating"}
    return {"needs_update": False, "status": "ready"}