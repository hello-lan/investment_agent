"""按标题拉取巨潮公告时间线。

只保留日期、类别、标题和链接，不下载正文。查询失败时仍写出「公告缺失」。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

SEARCH_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
ORG_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "http://www.cninfo.com.cn/new/index",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}

# 先匹配更具体的类别。纯定期报告标题会在 match_category 里被排除。
CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("处罚", ("行政处罚", "立案", "警示函", "监管措施", "纪律处分")),
    ("股权激励", ("股权激励", "股票期权", "限制性股票")),
    ("增减持", ("增持", "减持")),
    ("业绩预告", ("业绩预告", "业绩快报")),
    ("再融资回购", ("非公开发行", "向特定对象发行", "配股", "可转换公司债券", "可转债", "回购")),
    ("并购重组", ("收购", "并购", "重组", "吸收合并", "购买资产")),
    ("担保诉讼", ("担保", "诉讼", "仲裁", "判决")),
]

_PERIODIC = (
    "年度报告",
    "半年度报告",
    "半年报",
    "季度报告",
    "一季度报告",
    "三季度报告",
    "年报摘要",
    "半年报摘要",
)

DEFAULT_LIMIT = 40
MAX_PAGES = 8
PAGE_SIZE = 30


def match_category(title: str) -> str | None:
    """给公告标题归类。纯定期报告标题返回 None；标题里另有事项关键词时保留。"""
    text = (title or "").strip()
    if not text:
        return None
    hit = None
    for name, keywords in CATEGORIES:
        if any(keyword in text for keyword in keywords):
            hit = name
            break
    if hit is None:
        return None
    if any(key in text for key in _PERIODIC):
        stripped = text
        for key in _PERIODIC:
            stripped = stripped.replace(key, "")
        still = any(
            keyword in stripped
            for _, keywords in CATEGORIES
            for keyword in keywords
        )
        if not still:
            return None
    return hit


def parse_announcement_time(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        if text.isdigit():
            value = int(text)
        else:
            return None
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 10**12:
            stamp /= 1000.0
        try:
            return datetime.fromtimestamp(stamp)
        except (OSError, OverflowError, ValueError):
            return None
    return None


def announcement_link(code: str, item: dict) -> str:
    adjunct = str(item.get("adjunctUrl") or "").lstrip("/")
    if adjunct:
        return f"http://static.cninfo.com.cn/{adjunct}"
    announcement_id = item.get("announcementId") or ""
    return (
        "http://www.cninfo.com.cn/new/disclosure/detail"
        f"?stockCode={code}&announcementId={announcement_id}"
    )


def select_events(items: list[dict], code: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    chosen = []
    seen = set()
    for item in items:
        title = str(item.get("announcementTitle") or "").replace("<em>", "").replace("</em>", "")
        category = match_category(title)
        if category is None:
            continue
        when = parse_announcement_time(item.get("announcementTime"))
        link = announcement_link(code, item)
        key = (title, link)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(
            {
                "date": when.strftime("%Y-%m-%d") if when else "",
                "sort": when or datetime.min,
                "category": category,
                "title": title,
                "link": link,
            }
        )
    chosen.sort(key=lambda row: row["sort"], reverse=True)
    trimmed = chosen[: max(1, limit)]
    trimmed.sort(key=lambda row: (row["date"], row["title"]))
    for row in trimmed:
        row.pop("sort", None)
    return trimmed


def _plate(code: str) -> tuple[str, str]:
    if code.startswith(("6", "5")):
        return "sh", "sse"
    if code.startswith(("0", "3", "2")):
        return "sz", "szse"
    return "bj", "bj"


def _org_id(session: requests.Session, code: str) -> str | None:
    response = session.get(ORG_URL, timeout=15)
    response.raise_for_status()
    for stock in response.json().get("stockList", []):
        if stock.get("code") == code:
            return stock.get("orgId")
    return None


def fetch_announcements(code: str, start_date: str, end_date: str) -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    org_id = _org_id(session, code)
    if not org_id:
        raise RuntimeError(f"未找到股票 {code} 的 orgId")

    plate, column = _plate(code)
    collected: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        form = {
            "stock": f"{code},{org_id}",
            "tabName": "fulltext",
            "pageSize": str(PAGE_SIZE),
            "pageNum": str(page),
            "column": column,
            "category": "",
            "plate": plate,
            "seDate": f"{start_date}~{end_date}",
            "searchkey": "",
            "secid": "",
            "sortName": "announcementTime",
            "sortType": "desc",
            "isHLtitle": "true",
        }
        response = session.post(SEARCH_URL, data=form, timeout=20)
        response.raise_for_status()
        batch = response.json().get("announcements") or []
        if not batch:
            break
        collected.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    return collected


def render_markdown(code: str, start_year: int, end_year: int, events: list[dict], status: str, note: str = "") -> str:
    lines = [
        "# 公告时间线",
        "",
        f"code: {code}",
        f"range: {start_year}-{end_year}",
        f"status: {status}",
        f"count: {len(events)}",
    ]
    if note:
        lines.append(f"说明: {note}")
    lines.extend(["", "| 日期 | 类别 | 标题 | 链接 |", "| --- | --- | --- | --- |"])
    if not events:
        lines.append("|  |  |  |  |")
    for event in events:
        title = event["title"].replace("|", "\\|")
        lines.append(
            f"| {event['date']} | {event['category']} | {title} | {event['link']} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_events(
    code: str,
    start_year: int,
    end_year: int,
    project_root: Path | None = None,
    output: Path | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    root = (project_root or _PROJECT_ROOT).resolve()
    out = output or (root / "data" / "research" / code / "events.md")
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)

    start_date = f"{start_year}-01-01"
    end_date = datetime.now().strftime("%Y-%m-%d")
    try:
        raw = fetch_announcements(code, start_date, end_date)
        events = select_events(raw, code, limit=limit)
        text = render_markdown(code, start_year, end_year, events, status="ok")
        status = "ok"
        message = ""
    except Exception as exc:  # 网络或接口失败不阻断研究
        events = []
        message = "公告缺失"
        text = render_markdown(
            code,
            start_year,
            end_year,
            events,
            status="missing",
            note=f"{message}（{type(exc).__name__}）",
        )
        status = "missing"

    out.write_text(text, encoding="utf-8")
    rel = out.resolve().relative_to(root).as_posix() if out.resolve().is_relative_to(root) else out.as_posix()
    return {
        "status": status,
        "events_path": rel,
        "count": len(events),
        "message": message,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成公告标题时间线")
    parser.add_argument("--code", required=True)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--output", default="")
    parser.add_argument("--project-root", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    code = args.code.strip()
    if len(code) != 6 or not code.isdigit() or args.start_year > args.end_year:
        print(json.dumps({"status": "error", "message": "代码须为 6 位数字，且起始年不能大于结束年"}, ensure_ascii=False))
        return 2
    root = Path(args.project_root).resolve() if args.project_root else _PROJECT_ROOT
    output = Path(args.output) if args.output else None
    payload = build_events(
        code=code,
        start_year=args.start_year,
        end_year=args.end_year,
        project_root=root,
        output=output,
        limit=max(1, args.limit),
    )
    print(json.dumps({k: payload[k] for k in ("status", "events_path", "count", "message")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
