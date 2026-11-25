#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_FIELDS = ("chapter_id", "title", "line_start", "line_end", "priority", "reason")
REQUIRED_FINANCIAL_REPORT_CHAPTERS = {
    "financial_report_audit_report",
    "financial_report_consolidated_balance_sheet",
    "financial_report_consolidated_cash_flow_statement",
    "financial_report_consolidated_income_statement",
    "financial_report_accounting_policy",
    "financial_report_notes",
}
ALLOWED_CHILD_PARENTS = {"chapter_02", "chapter_03", "financial_report_notes"}


def validate_node(node: dict, *, parent_id: str | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    node_id = node.get("chapter_id", "<unknown>")

    for field in REQUIRED_FIELDS:
        if field not in node:
            errors.append(f"{node_id}: missing field {field}")

    line_start = node.get("line_start")
    line_end = node.get("line_end")
    if not isinstance(line_start, int) or not isinstance(line_end, int):
        errors.append(f"{node_id}: line_start/line_end must be integers")
    elif line_start > line_end:
        errors.append(f"{node_id}: line_start > line_end")

    priority = node.get("priority")
    if priority not in {"P0", "P1", "P2"}:
        warnings.append(f"{node_id}: unexpected priority {priority}")

    reason = str(node.get("reason", "")).strip()
    if reason in {"", "这是重要章节", "需要阅读"}:
        warnings.append(f"{node_id}: reason is empty or too generic")

    children = node.get("children")
    if children is not None and not isinstance(children, list):
        errors.append(f"{node_id}: children must be a list")
    if parent_id and children:
        errors.append(f"{node_id}: introduces a third level under {parent_id}")

    return errors, warnings


def validate(index_data: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    chapters = index_data.get("chapters") or []

    if not isinstance(chapters, list):
        return ["chapters must be a list"], warnings

    seen_ids: set[str] = set()
    last_start = 0
    last_end = 0
    found_financial_report_chapters: set[str] = set()

    for chapter in chapters:
        if not isinstance(chapter, dict):
            errors.append(f"chapter is not an object: {chapter!r}")
            continue

        chapter_errors, chapter_warnings = validate_node(chapter)
        errors.extend(chapter_errors)
        warnings.extend(chapter_warnings)

        chapter_id = chapter.get("chapter_id", "<unknown>")
        if chapter_id in seen_ids:
            errors.append(f"duplicate chapter_id: {chapter_id}")
        seen_ids.add(chapter_id)

        title = str(chapter.get("title", ""))
        if "财务报告" in title and not title.startswith("财务报告-"):
            errors.append(f"{chapter_id}: should not keep raw 财务报告 parent node")

        if chapter_id in REQUIRED_FINANCIAL_REPORT_CHAPTERS:
            found_financial_report_chapters.add(chapter_id)

        line_start = chapter.get("line_start")
        line_end = chapter.get("line_end")
        if isinstance(line_start, int) and isinstance(line_end, int):
            if line_start < last_start:
                errors.append(f"{chapter_id}: line_start is not monotonic")
            if line_start <= last_end:
                errors.append(f"{chapter_id}: overlaps previous top-level chapter")
            last_start = max(last_start, line_start)
            last_end = max(last_end, line_end)

        children = chapter.get("children") or []
        if children and chapter_id not in ALLOWED_CHILD_PARENTS:
            errors.append(f"{chapter_id}: unexpected children on non-expandable chapter")

        child_seen_ids: set[str] = set()
        child_last_start = 0
        child_last_end = 0
        for child in children:
            if not isinstance(child, dict):
                errors.append(f"{chapter_id}: child is not an object: {child!r}")
                continue

            child_errors, child_warnings = validate_node(child, parent_id=chapter_id)
            errors.extend(child_errors)
            warnings.extend(child_warnings)

            child_id = child.get("chapter_id", "<unknown>")
            if child_id in child_seen_ids:
                errors.append(f"{chapter_id}: duplicate child chapter_id: {child_id}")
            child_seen_ids.add(child_id)

            child_start = child.get("line_start")
            child_end = child.get("line_end")
            if isinstance(child_start, int) and isinstance(child_end, int):
                if isinstance(line_start, int) and child_start < line_start:
                    errors.append(f"{chapter_id}: child starts before parent at {child_id}")
                if isinstance(line_end, int) and child_end > line_end:
                    errors.append(f"{chapter_id}: child ends after parent at {child_id}")
                if child_start < child_last_start:
                    errors.append(f"{chapter_id}: child line_start is not monotonic at {child_id}")
                if child_start <= child_last_end:
                    errors.append(f"{chapter_id}: child overlaps previous child at {child_id}")
                child_last_start = max(child_last_start, child_start)
                child_last_end = max(child_last_end, child_end)

    missing_financial_report_chapters = sorted(REQUIRED_FINANCIAL_REPORT_CHAPTERS - found_financial_report_chapters)
    if missing_financial_report_chapters:
        warnings.append(
            "missing required financial report chapters: " + ", ".join(missing_financial_report_chapters)
        )

    if "chapter_02" not in seen_ids:
        warnings.append("missing chapter_02: expected 公司简介和主要财务指标 top-level chapter")
    if "chapter_03" not in seen_ids:
        warnings.append("missing chapter_03: expected 管理层讨论与分析 top-level chapter")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a hierarchical annual report chapter index JSON file.")
    parser.add_argument("index_path", type=Path)
    args = parser.parse_args()

    index_data = json.loads(args.index_path.read_text(encoding="utf-8"))
    errors, warnings = validate(index_data)
    print(json.dumps({"errors": errors, "warnings": warnings}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
