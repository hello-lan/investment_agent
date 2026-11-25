#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from index_common import (
    assign_top_level_line_ends,
    build_top_level_specs,
    default_output_path,
    detect_toc,
    extract_chapter_children,
    infer_company,
    infer_ticker_and_year,
    locate_financial_report_nodes,
    locate_node,
    locate_note_children,
    report_file_value,
    strip_heading_prefix,
)


def build_index(report_path: Path) -> tuple[dict, dict]:
    lines = report_path.read_text(encoding="utf-8").splitlines()
    company = infer_company(lines)
    ticker, year = infer_ticker_and_year(report_path, lines)
    toc_start, toc_end, toc_entries = detect_toc(lines)

    top_level_specs, financial_entry = build_top_level_specs(toc_entries)
    top_level_nodes = []
    missing_top_level: list[str] = []

    for spec in top_level_specs:
        found = locate_node(
            lines,
            chapter_id=spec.chapter_id,
            aliases=spec.aliases,
            priority=spec.priority,
            reason=spec.reason,
            toc_start=toc_start,
            toc_end=toc_end,
        )
        if found is None:
            missing_top_level.append(spec.toc_title)
            continue
        top_level_nodes.append(found)

    financial_nodes, missing_financial = locate_financial_report_nodes(
        lines, toc_start, toc_end, financial_entry
    )
    all_top_level = sorted(top_level_nodes + financial_nodes, key=lambda item: item.line_start)
    assign_top_level_line_ends(all_top_level, len(lines))

    for node in all_top_level:
        core_title = strip_heading_prefix(node.title)
        if "公司简介和主要财务指标" in core_title or "管理层讨论与分析" in core_title:
            node.children = extract_chapter_children(node, lines)
        if node.chapter_id == "financial_report_notes":
            node.children, node.line_end = locate_note_children(lines, node.line_start, node.line_end)

    chapters_json = [node.to_chapter().to_json() for node in all_top_level]
    output = {
        "report_file": report_file_value(report_path),
        "company": company,
        "ticker": ticker,
        "year": year,
        "index_version": 2,
        "chapters": chapters_json,
    }

    summary = {
        "report_path": str(report_path),
        "toc": {
            "line_start": toc_start,
            "line_end": toc_end,
            "entries": toc_entries,
        },
        "found_top_level_chapters": [node["title"] for node in chapters_json],
        "missing_top_level_chapters": missing_top_level,
        "missing_financial_report_nodes": missing_financial,
    }
    return output, summary


def validate_structure(index_data: dict) -> list[str]:
    errors: list[str] = []
    chapters = index_data.get("chapters", [])
    if not isinstance(chapters, list):
        return ["chapters must be a list"]

    last_end = 0
    seen_ids: set[str] = set()
    for chapter in chapters:
        if not isinstance(chapter, dict):
            errors.append(f"chapter is not an object: {chapter!r}")
            continue
        for field in ("chapter_id", "title", "line_start", "line_end", "priority", "reason"):
            if field not in chapter:
                errors.append(f"missing field {field} in chapter {chapter}")
        chapter_id = chapter.get("chapter_id")
        if chapter_id in seen_ids:
            errors.append(f"duplicate chapter_id: {chapter_id}")
        seen_ids.add(chapter_id)
        line_start = chapter.get("line_start")
        line_end = chapter.get("line_end")
        if not isinstance(line_start, int) or not isinstance(line_end, int):
            errors.append(f"{chapter_id}: line_start/line_end must be integers")
            continue
        if line_start > line_end:
            errors.append(f"{chapter_id}: line_start > line_end")
        if line_start <= last_end:
            errors.append(f"{chapter_id}: overlaps previous top-level chapter")
        last_end = line_end

        children = chapter.get("children") or []
        if not isinstance(children, list):
            errors.append(f"{chapter_id}: children must be a list")
            continue
        child_last_end = 0
        child_seen_ids: set[str] = set()
        for child in children:
            if not isinstance(child, dict):
                errors.append(f"{chapter_id}: child is not an object: {child!r}")
                continue
            for field in ("chapter_id", "title", "line_start", "line_end", "priority", "reason"):
                if field not in child:
                    errors.append(f"{chapter_id}: child missing field {field}: {child}")
            child_id = child.get("chapter_id")
            if child_id in child_seen_ids:
                errors.append(f"{chapter_id}: duplicate child chapter_id: {child_id}")
            child_seen_ids.add(child_id)
            child_start = child.get("line_start")
            child_end = child.get("line_end")
            if not isinstance(child_start, int) or not isinstance(child_end, int):
                errors.append(f"{chapter_id}: child line_start/line_end must be integers: {child}")
                continue
            if child_start > child_end:
                errors.append(f"{chapter_id}: child line_start > line_end at {child_id}")
            if child_start < line_start or child_end > line_end:
                errors.append(f"{chapter_id}: child range outside parent at {child_id}")
            if child_start <= child_last_end:
                errors.append(f"{chapter_id}: child overlaps previous child at {child_id}")
            child_last_end = child_end
            if child.get("children"):
                errors.append(f"{chapter_id}: child {child_id} introduces a third level")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a hierarchical annual report chapter index without reading the full report into model context."
    )
    parser.add_argument("report_path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    output_data, summary = build_index(args.report_path)
    errors = validate_structure(output_data)

    output_path = args.output or default_output_path(args.report_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2 if args.pretty else None),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {"output_path": str(output_path), "summary": summary, "validation_errors": errors},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
