"""财报排雷报告解析与扫描服务。"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ...config import ROOT_DIR

REPORTS_ROOT = ROOT_DIR / "data" / "reports"
REPORT_SUFFIX = "_财务排雷分析报告.md"

# 风险等级映射
RISK_LEVELS = {
    "极高风险": {"grade": "critical", "score": 1, "color": "danger"},
    "高风险": {"grade": "high", "score": 2, "color": "danger"},
    "存疑": {"grade": "warn", "score": 3, "color": "warn"},
    "暂未发现重大财务疑点": {"grade": "pass", "score": 4, "color": "pass"},
}

CONCLUSION_MAP = {
    "排除": "exclude",
    "继续跟踪": "track",
    "保留观察": "watch",
}


def _extract_field(text: str, pattern: str, group: int = 1) -> str | None:
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    return m.group(group).strip() if m else None


def parse_forensic_report(text: str, file_path: str | None = None) -> dict:
    """从排雷报告 Markdown 提取结构化字段。"""
    code = _extract_field(text, r"\*\*公司：\*\*\s*[^\d]*(\d{6})")
    if not code and file_path:
        m = re.search(r"/(\d{6})/", file_path.replace("\\", "/"))
        code = m.group(1) if m else None

    company = _extract_field(text, r"\*\*公司：\*\*\s*(.+?)(?:\n|$)")
    report_period = _extract_field(text, r"\*\*报告期：\*\*\s*(.+?)(?:\n|$)")
    analysis_date = _extract_field(text, r"\*\*分析日期：\*\*\s*(.+?)(?:\n|$)")
    data_quality = _extract_field(text, r"\*\*数据完整度：\*\*\s*(.+?)(?:\n|$)")
    confidence = _extract_field(text, r"\*\*分析置信度：\*\*\s*(.+?)(?:\n|$)")

    risk_raw = _extract_field(text, r"\*\*总体评级：\*\*\s*(.+?)(?:\n|$)")
    conclusion_raw = _extract_field(text, r"\*\*结论：\*\*\s*(.+?)(?:\n|$)")

    risk_meta = RISK_LEVELS.get(risk_raw or "", {"grade": "unknown", "score": 0, "color": "neutral"})
    conclusion_key = CONCLUSION_MAP.get(conclusion_raw or "", "unknown")

    drivers = re.findall(r"^\d+\.\s*(.+)$", _extract_field(
        text, r"\*\*主要驱动因素.*?\*\*[\s\S]*?\n((?:\d+\..+\n?)+)", group=1
    ) or "", re.MULTILINE)

    audit = _extract_field(text, r"\*\*审计意见：\*\*\s*(.+?)(?:\n|$)")

    red_flags = []
    for section in ["利润表疑点", "资产负债表疑点", "现金流量表疑点"]:
        sec_match = re.search(rf"## .*?{section}([\s\S]*?)(?=## |\Z)", text)
        if not sec_match:
            continue
        sec_text = sec_match.group(1)
        for m in re.finditer(r"### 疑点 \d+：(.+?)\n([\s\S]*?)(?=### 疑点|\*\*阶段小结|\Z)", sec_text):
            name = m.group(1).strip()
            rule = _extract_field(m.group(0), r"\*\*规则依据：\*\*\s*(.+?)(?:\n|$)") or ""
            red_flags.append({"section": section.replace("疑点", ""), "name": name, "rule": rule})

    cf_portrait = _extract_field(text, r"\*\*现金流量肖像：\*\*\s*(.+?)(?:\n|$)")

    return {
        "code": code,
        "company": company,
        "report_period": report_period,
        "analysis_date": analysis_date,
        "data_quality": data_quality,
        "confidence": confidence,
        "risk_level": risk_raw,
        "risk_grade": risk_meta["grade"],
        "risk_score": risk_meta["score"],
        "risk_color": risk_meta["color"],
        "conclusion": conclusion_raw,
        "conclusion_key": conclusion_key,
        "drivers": drivers[:4],
        "audit_opinion": audit,
        "red_flags": red_flags[:20],
        "red_flag_count": len(red_flags),
        "cf_portrait": cf_portrait,
        "file_path": file_path,
    }


def scan_forensic_reports() -> list[dict]:
    """扫描 data/reports 下所有排雷报告。"""
    results = []
    if not REPORTS_ROOT.exists():
        return results

    for md_file in REPORTS_ROOT.rglob(f"*{REPORT_SUFFIX}"):
        try:
            text = md_file.read_text(encoding="utf-8")
            rel = str(md_file.relative_to(ROOT_DIR)).replace("\\", "/")
            parsed = parse_forensic_report(text, rel)
            parsed["file_path"] = rel
            parsed["updated_at"] = datetime.fromtimestamp(
                md_file.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            results.append(parsed)
        except Exception:
            continue

    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results


def get_report_by_code(code: str) -> dict | None:
    """获取指定股票的最新排雷报告。"""
    code = code.strip()
    matches = [r for r in scan_forensic_reports() if r.get("code") == code]
    return matches[0] if matches else None


def get_report_detail(file_path: str) -> dict | None:
    """按文件路径获取完整报告（含原文摘要）。"""
    full = ROOT_DIR / file_path if not Path(file_path).is_absolute() else Path(file_path)
    if not full.exists():
        return None
    text = full.read_text(encoding="utf-8")
    parsed = parse_forensic_report(text, str(full.relative_to(ROOT_DIR)).replace("\\", "/"))
    parsed["content_preview"] = text[:8000]
    return parsed


def save_report_json(parsed: dict, output_dir: Path) -> Path:
    """将结构化结果保存为 JSON（供看板/API 使用）。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    code = parsed.get("code") or "unknown"
    out = output_dir / f"{code}_forensic_summary.json"
    out.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
