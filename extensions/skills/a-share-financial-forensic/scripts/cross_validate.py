#!/usr/bin/env python3
"""年报 MD 解析结果 vs AKShare 第三方数据交叉验证。

用法:
    python3 cross_validate.py --code 600519 --manifest data/reports/600519/4_output/data_manifest.md
    python3 cross_validate.py --code 600519 --manifest data/reports/600519/4_output/data_manifest.md --output data/reports/600519/4_output/crosscheck_report.md
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path


# 关键科目：manifest 显示名 → AKShare 字段映射
CHECK_ITEMS = [
    {
        "label": "营业总收入",
        "manifest_patterns": [r"营业总收入", r"营业收入", r"一、营业总收入"],
        "ak_field": "operate_income",
        "ak_table": "income",
    },
    {
        "label": "归母净利润",
        "manifest_patterns": [r"归属于母公司.*净利润", r"归母净利润"],
        "ak_field": "parent_netprofit",
        "ak_table": "income",
    },
    {
        "label": "资产总计",
        "manifest_patterns": [r"资产总计", r"资产合计"],
        "ak_field": "total_assets",
        "ak_table": "balance",
    },
    {
        "label": "经营现金流净额",
        "manifest_patterns": [r"经营活动.*现金流量净额"],
        "ak_field": "netcash_operate",
        "ak_table": "cashflow",
    },
]


def _parse_manifest_table(manifest_text: str, chapter: str, item_patterns: list[str], year: str) -> float | None:
    """从 data_manifest.md 的多 year 对比表中提取某年某科目的数值。"""
    section_match = re.search(
        rf"### {re.escape(chapter)}[\s\S]*?\| 项目 \|(.+)\|\n\|[-| ]+\|\n((?:\|.+\|\n)+)",
        manifest_text,
    )
    if not section_match:
        return None

    header = section_match.group(1)
    years = [y.strip() for y in header.split("|")]
    if year not in years:
        return None
    year_idx = years.index(year)

    for line in section_match.group(2).strip().split("\n"):
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 2:
            continue
        item_name = cols[1]
        for pat in item_patterns:
            if re.search(pat, item_name):
                val_str = cols[year_idx + 1] if year_idx + 1 < len(cols) else ""
                val_str = val_str.replace(",", "").replace("，", "").strip()
                if val_str in ("-", "", "—"):
                    return None
                try:
                    return float(val_str)
                except ValueError:
                    return None
    return None


def _normalize_amount(v: float) -> float:
    """统一为元"""
    return v


async def _fetch_akshare_data(code: str, year: str) -> dict:
    import akshare as ak

    report_date = f"{year}-12-31"
    symbol = f"SH{code}" if code.startswith("6") else f"SZ{code}"
    loop = asyncio.get_event_loop()

    result = {"report_date": report_date}

    fetchers = {
        "income": (ak.stock_profit_sheet_by_report_em, symbol),
        "balance": (ak.stock_balance_sheet_by_report_em, symbol),
        "cashflow": (ak.stock_cash_flow_sheet_by_report_em, symbol),
    }

    for table, (func, sym) in fetchers.items():
        try:
            df = await loop.run_in_executor(None, func, sym)
            row = df[df["REPORT_DATE"].astype(str).str.startswith(report_date)]
            if len(row) > 0:
                result[table] = row.iloc[0].to_dict()
            else:
                result[table] = {}
        except Exception as e:
            result[table] = {"_error": str(e)}

    return result


def _compare(manifest_val: float | None, ak_val: float | None, label: str) -> dict:
    if manifest_val is None and ak_val is None:
        return {"label": label, "status": "missing", "note": "双方均无数据"}
    if manifest_val is None:
        return {"label": label, "status": "manifest_missing", "akshare": ak_val, "note": "年报解析缺失"}
    if ak_val is None:
        return {"label": label, "status": "akshare_missing", "manifest": manifest_val, "note": "AKShare 缺失"}
    if manifest_val == 0 and ak_val == 0:
        return {"label": label, "status": "pass", "manifest": manifest_val, "akshare": ak_val, "diff_pct": 0}

    diff = abs(manifest_val - ak_val)
    base = max(abs(manifest_val), abs(ak_val), 1)
    diff_pct = diff / base * 100

    status = "pass" if diff_pct < 3 else ("warn" if diff_pct < 10 else "fail")
    return {
        "label": label,
        "status": status,
        "manifest": manifest_val,
        "akshare": ak_val,
        "diff": diff,
        "diff_pct": round(diff_pct, 2),
        "note": "一致" if status == "pass" else f"偏差 {diff_pct:.1f}%",
    }


async def run_crosscheck(code: str, manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {"error": f"文件不存在: {manifest_path}"}

    manifest_text = manifest_path.read_text(encoding="utf-8")
    years = re.findall(r"\| 项目 \| (.+?) \|", manifest_text)
    if not years:
        return {"error": "无法从 manifest 解析年份列"}

    year_cols = [y.strip() for y in years[0].split("|")]
    check_years = [y for y in year_cols if re.match(r"^\d{4}$", y)][-3:]

    all_results = []
    for year in check_years:
        ak_data = await _fetch_akshare_data(code, year)
        year_results = {"year": year, "items": []}

        chapter_map = {
            "income": "合并利润表",
            "balance": "合并资产负债表",
            "cashflow": "合并现金流量表",
        }

        for item in CHECK_ITEMS:
            table = item["ak_table"]
            ak_row = ak_data.get(table, {})
            ak_val = ak_row.get(item["ak_field"].upper()) if isinstance(ak_row, dict) else None
            if ak_val is None and isinstance(ak_row, dict):
                ak_val = ak_row.get(item["ak_field"])
            ak_val = float(ak_val) if ak_val is not None else None

            manifest_val = _parse_manifest_table(
                manifest_text, chapter_map[table], item["manifest_patterns"], year
            )

            year_results["items"].append(_compare(manifest_val, ak_val, item["label"]))

        all_results.append(year_results)

    fail_count = sum(
        1 for yr in all_results for it in yr["items"] if it["status"] == "fail"
    )
    warn_count = sum(
        1 for yr in all_results for it in yr["items"] if it["status"] == "warn"
    )

    return {
        "code": code,
        "years_checked": check_years,
        "results": all_results,
        "summary": {
            "fail_count": fail_count,
            "warn_count": warn_count,
            "overall": "pass" if fail_count == 0 and warn_count == 0 else ("warn" if fail_count == 0 else "fail"),
        },
    }


def _render_markdown(result: dict) -> str:
    lines = [
        "# 第三方数据交叉验证报告",
        "",
        f"**股票代码：** {result.get('code')}",
        f"**验证年份：** {', '.join(result.get('years_checked', []))}",
        f"**总体结论：** {result.get('summary', {}).get('overall', 'unknown')}",
        "",
    ]

    for yr in result.get("results", []):
        lines.append(f"## {yr['year']} 年")
        lines.append("")
        lines.append("| 科目 | 年报解析 | AKShare | 偏差% | 状态 |")
        lines.append("|------|---------|---------|-------|------|")
        for it in yr["items"]:
            m = it.get("manifest", "-")
            a = it.get("akshare", "-")
            d = it.get("diff_pct", "-")
            lines.append(f"| {it['label']} | {m} | {a} | {d} | {it['status']} |")
        lines.append("")

    lines.append("> 偏差 <3% 为 pass，3-10% 为 warn，>10% 为 fail。大偏差可能源于 PDF 解析错漏或口径差异。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="年报 MD vs AKShare 交叉验证")
    parser.add_argument("--code", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    result = asyncio.run(run_crosscheck(args.code.strip(), Path(args.manifest)))
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_render_markdown(result), encoding="utf-8")
        print(f"报告已写入: {out}", file=sys.stderr)

    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
