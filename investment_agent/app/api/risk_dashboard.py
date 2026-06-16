"""排雷看板 API"""

from fastapi import APIRouter, HTTPException, Query

from ..services.forensic_report import (
    get_report_by_code,
    get_report_detail,
    scan_forensic_reports,
)

router = APIRouter(prefix="/api/risk-dashboard", tags=["risk-dashboard"])


@router.get("/reports")
async def list_reports(
    q: str = Query(default="", description="按代码或公司名过滤"),
    grade: str = Query(default="", description="风险等级过滤: critical/high/warn/pass"),
):
    reports = scan_forensic_reports()
    if q:
        q = q.strip().lower()
        reports = [
            r for r in reports
            if q in (r.get("code") or "").lower()
            or q in (r.get("company") or "").lower()
        ]
    if grade:
        reports = [r for r in reports if r.get("risk_grade") == grade]

    summary = {
        "total": len(reports),
        "critical": sum(1 for r in reports if r.get("risk_grade") == "critical"),
        "high": sum(1 for r in reports if r.get("risk_grade") == "high"),
        "warn": sum(1 for r in reports if r.get("risk_grade") == "warn"),
        "pass": sum(1 for r in reports if r.get("risk_grade") == "pass"),
    }
    return {"summary": summary, "reports": reports}


@router.get("/reports/{code}")
async def get_report(code: str):
    report = get_report_by_code(code.strip())
    if not report:
        raise HTTPException(status_code=404, detail=f"未找到 {code} 的排雷报告")
    return report


@router.get("/detail")
async def get_detail(path: str = Query(..., description="报告相对路径")):
    report = get_report_detail(path)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report
