"""扫描本地材料，生成多年研究的语料清单。

只登记路径、类型、哈希和证据包是否过期，不读取正文、不下结论。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

_ANNUAL_KEYS = ("年度报告", "年报")
_HALF_KEYS = ("半年度报告", "半年报", "中期报告")
_QUARTER_KEYS = ("季度报告", "季报")
_TAG_RANK = {"q1": 1, "half": 2, "q3": 3, "interim": 2, "annual": 0}
_SHA_RE = re.compile(r"^source_sha256:\s*([0-9a-fA-F]{64})\s*$")


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def report_year(name: str) -> int | None:
    matched = re.search(r"(20\d{2})年", name)
    if matched:
        return int(matched.group(1))
    years = re.findall(r"20\d{2}", name)
    return int(years[0]) if years else None


def classify_filing(name: str) -> tuple[str, str] | None:
    """返回 (doc_type, tag)。无法识别为定期报告时返回 None。"""
    if any(key in name for key in _HALF_KEYS):
        return "interim", "half"
    if "第三季" in name or "三季" in name:
        return "interim", "q3"
    if "第一季" in name or "一季" in name:
        return "interim", "q1"
    if any(key in name for key in _QUARTER_KEYS):
        return "interim", "interim"
    if any(key in name for key in _ANNUAL_KEYS):
        return "annual", "annual"
    return None


def _slug(stem: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", stem)
    text = text.strip("._") or "doc"
    return text[:48]


def find_index(md_path: Path, root: Path) -> str | None:
    stem = md_path.stem
    parent = md_path.parent
    preferred = [
        parent / f"{stem}.sections.json",
        parent / f"{stem}.built.sections.json",
        parent / f"{stem}.generated.sections.json",
    ]
    for candidate in preferred:
        if candidate.is_file():
            return _rel(candidate, root)
    others = sorted(parent.glob(f"{stem}*.sections.json"))
    if others:
        return _rel(others[0], root)
    return None


def _evidence_is_current(evidence_path: Path, source_sha: str) -> bool:
    if not evidence_path.is_file():
        return False
    try:
        lines = evidence_path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]
    except OSError:
        return False
    for line in lines:
        matched = _SHA_RE.match(line.strip())
        if matched and matched.group(1).lower() == source_sha.lower():
            return True
    return False


def _iter_md(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = []
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        if any(part in {"evidence", "1_pdf", "3_split"} for part in path.parts):
            continue
        files.append(path)
    return files


def _prefer(left: dict, right: dict) -> dict:
    """同一年报保留有索引的那份，其次保留 md 目录下的那份。"""
    if bool(left.get("index_path")) != bool(right.get("index_path")):
        return left if left.get("index_path") else right
    left_md = "/md/" in f"/{left['path']}/"
    right_md = "/md/" in f"/{right['path']}/"
    if left_md != right_md:
        return left if left_md else right
    return left if len(left["path"]) <= len(right["path"]) else right


def _collect(root: Path, code: str) -> tuple[list[dict], list[dict]]:
    filing_roots = [
        root / "data" / "reports" / "md" / code,
        root / "data" / "reports" / code / "2_markdown",
    ]
    source_root = root / "data" / "research" / code / "sources"
    filings: list[dict] = []
    third: list[dict] = []

    for directory in filing_roots:
        for path in _iter_md(directory):
            kind = classify_filing(path.name)
            if kind is None:
                continue
            doc_type, tag = kind
            year = report_year(path.name)
            if year is None:
                continue
            filings.append(
                {
                    "path": _rel(path, root),
                    "abs": path,
                    "year": year,
                    "doc_type": doc_type,
                    "tag": tag,
                    "trust": "filing",
                    "index_path": find_index(path, root),
                }
            )

    for path in _iter_md(source_root):
        year = report_year(path.name)
        third.append(
            {
                "path": _rel(path, root),
                "abs": path,
                "year": year,
                "doc_type": "third_party",
                "tag": "third",
                "trust": "third_party",
            }
        )
    return filings, third


def _dedupe_annuals(filings: list[dict]) -> list[dict]:
    chosen: dict[int, dict] = {}
    for item in filings:
        if item["doc_type"] != "annual":
            continue
        year = item["year"]
        current = chosen.get(year)
        chosen[year] = item if current is None else _prefer(current, item)
    return [chosen[year] for year in sorted(chosen)]


def _latest_interim(filings: list[dict], after_year: int) -> dict | None:
    later = [
        item
        for item in filings
        if item["doc_type"] == "interim" and item["year"] > after_year
    ]
    if not later:
        return None
    best: dict | None = None
    for item in later:
        if best is None:
            best = item
            continue
        rank = (item["year"], _TAG_RANK.get(item["tag"], 0))
        best_rank = (best["year"], _TAG_RANK.get(best["tag"], 0))
        if rank > best_rank:
            best = item
        elif rank == best_rank:
            best = _prefer(best, item)
    return best


def _doc_id(item: dict, used: set[str]) -> str:
    if item["doc_type"] == "annual":
        base = f"{item['year']}_annual"
    elif item["doc_type"] == "interim":
        base = f"{item['year']}_{item['tag']}"
    else:
        stem = Path(item["path"]).stem
        year = item.get("year")
        prefix = f"{year}_" if year else ""
        base = f"{prefix}third_{_slug(stem)}"
    candidate = base
    serial = 2
    while candidate in used:
        candidate = f"{base}_{serial}"
        serial += 1
    used.add(candidate)
    return candidate


def build_corpus(
    code: str,
    start_year: int,
    end_year: int,
    project_root: Path | None = None,
    output: Path | None = None,
) -> dict:
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("股票代码须为 6 位数字")
    if start_year > end_year:
        raise ValueError("start_year 不能大于 end_year")

    root = (project_root or _PROJECT_ROOT).resolve()
    filings, third = _collect(root, code)
    annuals = [
        item
        for item in _dedupe_annuals(filings)
        if start_year <= item["year"] <= end_year
    ]
    selected = list(annuals)
    latest_annual = annuals[-1]["year"] if annuals else None
    if latest_annual is not None:
        supplement = _latest_interim(filings, latest_annual)
        if supplement is not None:
            supplement = dict(supplement)
            supplement["supplement"] = True
            selected.append(supplement)

    for item in third:
        selected.append(dict(item))

    used_ids: set[str] = set()
    documents = []
    for item in selected:
        doc_id = _doc_id(item, used_ids)
        source = item["abs"]
        source_sha = _sha256(source)
        evidence_rel = f"data/research/{code}/evidence/{doc_id}.md"
        evidence_abs = root / evidence_rel
        current = _evidence_is_current(evidence_abs, source_sha)
        index_path = item.get("index_path") if item["trust"] == "filing" else None
        documents.append(
            {
                "doc_id": doc_id,
                "year": item.get("year"),
                "doc_type": item["doc_type"],
                "tag": item["tag"],
                "trust": item["trust"],
                "supplement": bool(item.get("supplement")),
                "path": item["path"],
                "index_path": index_path,
                "sha256": source_sha,
                "evidence_path": evidence_rel,
                "evidence_status": "current" if current else ("stale" if evidence_abs.is_file() else "missing"),
            }
        )

    annual_years = {item["year"] for item in annuals}
    missing = [year for year in range(start_year, end_year + 1) if year not in annual_years]
    payload = {
        "code": code,
        "start_year": start_year,
        "end_year": end_year,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources_dir": f"data/research/{code}/sources",
        "events_path": f"data/research/{code}/events.md",
        "memo_path": f"data/research/{code}/{start_year}-{end_year}_research.md",
        "notes_path": f"data/research/{code}/notes.md",
        "missing_annual_years": missing,
        "documents": documents,
    }

    out = output or (root / "data" / "research" / code / "corpus.json")
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["corpus_path"] = _rel(out, root) if out.is_relative_to(root) else out.as_posix()
    return payload


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成多年研究语料清单")
    parser.add_argument("--code", required=True, help="6 位股票代码")
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--output", default="", help="清单输出路径，默认 data/research/{code}/corpus.json")
    parser.add_argument("--project-root", default="", help="项目根，测试时使用")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.project_root).resolve() if args.project_root else _PROJECT_ROOT
    output = Path(args.output) if args.output else None
    try:
        payload = build_corpus(
            code=args.code.strip(),
            start_year=args.start_year,
            end_year=args.end_year,
            project_root=root,
            output=output,
        )
    except ValueError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2

    summary = {
        "status": "ok",
        "corpus_path": payload["corpus_path"],
        "documents": len(payload["documents"]),
        "missing_annual_years": payload["missing_annual_years"],
        "needs_extract": [
            doc["doc_id"]
            for doc in payload["documents"]
            if doc["evidence_status"] != "current"
        ],
        "needs_index": [
            doc["doc_id"]
            for doc in payload["documents"]
            if doc["trust"] == "filing" and not doc["index_path"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
