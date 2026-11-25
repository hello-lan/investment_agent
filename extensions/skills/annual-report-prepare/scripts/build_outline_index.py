#!/usr/bin/env python3
"""Build section index from PDF bookmarks, mapped onto Markdown line numbers."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from index_common import (
    CHAPTER_CHILD_RULES,
    FINANCIAL_REPORT_SPECS,
    TOP_LEVEL_RULES,
    ChapterNode,
    LocatedNode,
    assign_top_level_line_ends,
    chapter_order_from_prefix,
    classify_title,
    clean_bookmark_title,
    default_output_path,
    detect_toc,
    extract_chapter_children,
    find_page_line_window,
    infer_company,
    infer_ticker_and_year,
    is_expandable_profile_or_mda,
    locate_node,
    locate_note_children,
    match_financial_spec,
    normalize,
    report_file_value,
    split_section_title,
    strip_heading_prefix,
)


MIN_LOCATED_TOP_LEVEL = 3
_PAGE_PAD_PAGES = 3


@dataclass(frozen=True)
class OutlineNode:
    title: str
    depth: int
    page: int  # 0-based
    path: tuple[str, ...]


def _ensure_package(package_name: str, import_name: str | None = None) -> None:
    module_name = import_name or package_name
    try:
        __import__(module_name)
        return
    except ImportError:
        pass

    print(f"[build-outline-index] 缺少依赖: {package_name}，正在自动安装...", file=sys.stderr)
    uv = shutil.which("uv")
    if uv:
        try:
            subprocess.check_call(
                [uv, "pip", "install", package_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            __import__(module_name)
            print(f"[build-outline-index] 安装完成: {package_name}", file=sys.stderr)
            return
        except (subprocess.CalledProcessError, ImportError):
            pass

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", package_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        __import__(module_name)
        print(f"[build-outline-index] 安装完成: {package_name}", file=sys.stderr)
    except (subprocess.CalledProcessError, ImportError) as exc:
        print(f"[build-outline-index] 无法安装 {package_name}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def read_outline(doc) -> list[OutlineNode]:
    try:
        toc = doc.get_toc(simple=True) or []
    except Exception as exc:  # noqa: BLE001 — outline is best-effort
        print(f"[build-outline-index] 读取书签失败: {exc}", file=sys.stderr)
        return []

    nodes: list[OutlineNode] = []
    stack: list[str] = []
    for entry in toc:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        level, raw_title, page1 = entry[0], entry[1], entry[2]
        try:
            level_num = int(level)
            page1_num = int(page1)
        except (TypeError, ValueError):
            continue
        if level_num < 1 or page1_num < 1:
            continue
        title = clean_bookmark_title(str(raw_title))
        if not title:
            continue
        depth = level_num - 1
        stack = stack[:depth]
        stack.append(title)
        nodes.append(
            OutlineNode(
                title=title,
                depth=depth,
                page=page1_num - 1,
                path=tuple(stack),
            )
        )
    return nodes


def _path_under_financial_report(path: tuple[str, ...]) -> bool:
    return any("财务报告" in part or "财务会计报告" in part for part in path)


def _aliases_for_title(title: str) -> list[str]:
    prefix, name = split_section_title(title)
    aliases = [title]
    if prefix and name:
        aliases.extend([f"{prefix} {name}", f"{prefix}{name}", name])
    elif name:
        aliases.append(name)
    core = strip_heading_prefix(title)
    if core and core not in aliases:
        aliases.append(core)
    # de-dupe while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for alias in aliases:
        key = alias.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def locate_with_page_hint(
    lines: list[str],
    *,
    chapter_id: str,
    aliases: list[str],
    priority: str,
    reason: str,
    page_0based: int,
    toc_start: int,
    toc_end: int,
    search_start: int = 1,
    search_end: int | None = None,
    pass_name: str = "outline",
) -> LocatedNode | None:
    page_1based = page_0based + 1
    hard_end = search_end if search_end is not None else len(lines)

    window = find_page_line_window(lines, page_1based)
    if window is not None:
        win_start, win_end = window
        # Allow a few pages after the bookmark page — headings often land near the mark.
        padded_end = win_end
        for offset in range(1, _PAGE_PAD_PAGES + 1):
            next_window = find_page_line_window(lines, page_1based + offset)
            if next_window is None:
                break
            padded_end = next_window[1]
        local_start = max(search_start, win_start)
        local_end = min(hard_end, padded_end)
        found = locate_node(
            lines,
            chapter_id=chapter_id,
            aliases=aliases,
            priority=priority,
            reason=reason,
            toc_start=toc_start,
            toc_end=toc_end,
            search_start=local_start,
            search_end=local_end,
            pass_name=f"{pass_name}_page",
        )
        if found is not None:
            return found

    return locate_node(
        lines,
        chapter_id=chapter_id,
        aliases=aliases,
        priority=priority,
        reason=reason,
        toc_start=toc_start,
        toc_end=toc_end,
        search_start=search_start,
        search_end=hard_end,
        pass_name=pass_name,
    )


def _chapter_id_for_top_level(title: str, fallback_order: int) -> str:
    prefix, _name = split_section_title(title)
    if prefix:
        order = chapter_order_from_prefix(prefix)
        if order:
            return f"chapter_{order:02d}"
    return f"chapter_{fallback_order:02d}"


def _collect_bookmark_children(
    nodes: list[OutlineNode],
    parent_path: tuple[str, ...],
) -> list[OutlineNode]:
    """Direct children bookmarks under parent_path (depth == len(parent_path))."""
    parent_depth = len(parent_path)
    children: list[OutlineNode] = []
    for node in nodes:
        if node.depth != parent_depth:
            continue
        if node.path[:parent_depth] != parent_path:
            continue
        children.append(node)
    return children


def _children_from_bookmarks(
    parent: LocatedNode,
    child_bookmarks: list[OutlineNode],
    lines: list[str],
    toc_start: int,
    toc_end: int,
) -> list[ChapterNode]:
    children: list[ChapterNode] = []
    child_index = 1
    for bookmark in child_bookmarks:
        aliases = _aliases_for_title(bookmark.title)
        found = locate_with_page_hint(
            lines,
            chapter_id=f"{parent.chapter_id}_item_{child_index:02d}",
            aliases=aliases,
            priority=parent.priority,
            reason=f"{strip_heading_prefix(parent.title)}章节内小节，便于定向回查",
            page_0based=bookmark.page,
            toc_start=toc_start,
            toc_end=toc_end,
            search_start=parent.line_start,
            search_end=parent.line_end,
            pass_name="outline_child",
        )
        if found is None:
            continue
        if found.line_start < parent.line_start or found.line_start > parent.line_end:
            continue
        priority, reason = classify_title(
            found.title,
            CHAPTER_CHILD_RULES,
            parent.priority,
            f"{strip_heading_prefix(parent.title)}章节内小节，便于定向回查",
        )
        children.append(
            ChapterNode(
                chapter_id=f"{parent.chapter_id}_item_{child_index:02d}",
                title=found.title,
                line_start=found.line_start,
                line_end=0,
                priority=priority,
                reason=reason,
            )
        )
        child_index += 1

    for index, child in enumerate(children):
        next_start = (
            children[index + 1].line_start if index < len(children) - 1 else parent.line_end + 1
        )
        child.line_end = max(child.line_start, next_start - 1)
    return children


def build_index(pdf_path: Path, md_path: Path) -> tuple[dict, dict]:
    import pymupdf

    lines = md_path.read_text(encoding="utf-8").splitlines()
    company = infer_company(lines)
    ticker, year = infer_ticker_and_year(md_path, lines)
    toc_start, toc_end, _toc_entries = detect_toc(lines)

    doc = pymupdf.open(str(pdf_path))
    try:
        outline = read_outline(doc)
    finally:
        doc.close()

    if not outline:
        raise RuntimeError("PDF 无可用书签大纲")

    top_level_nodes: list[LocatedNode] = []
    financial_nodes: list[LocatedNode] = []
    missing_top_level: list[str] = []
    missing_financial: list[str] = []
    seen_financial_ids: set[str] = set()
    fallback_order = 1

    # Depth-0 section chapters (skip 财务报告 parent).
    for node in outline:
        if node.depth != 0:
            continue
        if "财务报告" in node.title or "财务会计报告" in node.title:
            continue

        chapter_id = _chapter_id_for_top_level(node.title, fallback_order)
        fallback_order += 1
        priority, reason = classify_title(
            strip_heading_prefix(node.title),
            TOP_LEVEL_RULES,
            "P2",
            "用于按目录章节定向回查",
        )
        found = locate_with_page_hint(
            lines,
            chapter_id=chapter_id,
            aliases=_aliases_for_title(node.title),
            priority=priority,
            reason=reason,
            page_0based=node.page,
            toc_start=toc_start,
            toc_end=toc_end,
            pass_name="outline_top",
        )
        if found is None:
            missing_top_level.append(node.title)
            continue
        # Prefer bookmark wording when MD title is noisy but keep MD line hit title if close.
        found.chapter_id = chapter_id
        top_level_nodes.append(found)

    # Financial report entries: any bookmark under 财务报告 path, or orphan specs.
    for node in outline:
        if not _path_under_financial_report(node.path) and node.depth == 0:
            # Orphan elevated financial titles (rare).
            if match_financial_spec(node.title) is None:
                continue
        elif not _path_under_financial_report(node.path):
            continue

        spec = match_financial_spec(node.title)
        if spec is None:
            continue
        if spec["chapter_id"] in seen_financial_ids:
            continue

        found = locate_with_page_hint(
            lines,
            chapter_id=spec["chapter_id"],
            aliases=list(spec["aliases"]) + _aliases_for_title(node.title),
            priority=spec["priority"],
            reason=spec["reason"],
            page_0based=node.page,
            toc_start=toc_start,
            toc_end=toc_end,
            pass_name="outline_finance",
        )
        if found is None:
            missing_financial.append(spec["chapter_id"])
            continue
        found.title = f"财务报告-{strip_heading_prefix(found.title)}"
        found.chapter_id = spec["chapter_id"]
        financial_nodes.append(found)
        seen_financial_ids.add(spec["chapter_id"])

    # Fill financial specs that bookmarks named differently — bounded search after finance root.
    finance_root_page = None
    for node in outline:
        if node.depth == 0 and ("财务报告" in node.title or "财务会计报告" in node.title):
            finance_root_page = node.page
            break

    finance_search_start = 1
    if finance_root_page is not None:
        root = locate_with_page_hint(
            lines,
            chapter_id="financial_report_root",
            aliases=["财务报告", "财务会计报告", "第十二节 财务报告", "第十节 财务报告"],
            priority="P0",
            reason="财务报告总入口",
            page_0based=finance_root_page,
            toc_start=toc_start,
            toc_end=toc_end,
            pass_name="outline_finance_root",
        )
        if root is not None:
            finance_search_start = root.line_start

    for spec in FINANCIAL_REPORT_SPECS:
        if spec["chapter_id"] in seen_financial_ids:
            continue
        found = locate_node(
            lines,
            chapter_id=spec["chapter_id"],
            aliases=spec["aliases"],
            priority=spec["priority"],
            reason=spec["reason"],
            toc_start=toc_start,
            toc_end=toc_end,
            search_start=finance_search_start,
            search_end=len(lines),
            pass_name="outline_finance_fill",
        )
        if found is None:
            if spec["chapter_id"] not in missing_financial:
                missing_financial.append(spec["chapter_id"])
            continue
        found.title = f"财务报告-{strip_heading_prefix(found.title)}"
        financial_nodes.append(found)
        seen_financial_ids.add(spec["chapter_id"])

    all_top_level = sorted(top_level_nodes + financial_nodes, key=lambda item: item.line_start)
    if len(all_top_level) < MIN_LOCATED_TOP_LEVEL:
        raise RuntimeError(
            f"书签定位后顶层章节过少（{len(all_top_level)} < {MIN_LOCATED_TOP_LEVEL}）"
        )

    assign_top_level_line_ends(all_top_level, len(lines))

    # Children: bookmark-first for profile/MDA, else bounded scan; notes always scan.
    for node in all_top_level:
        if is_expandable_profile_or_mda(node.title):
            parent_bookmark = next(
                (
                    candidate
                    for candidate in outline
                    if candidate.depth == 0 and normalize_title_match(candidate.title, node.title)
                ),
                None,
            )
            child_nodes: list[ChapterNode] = []
            if parent_bookmark is not None:
                bookmarks = _collect_bookmark_children(outline, parent_bookmark.path)
                child_nodes = _children_from_bookmarks(
                    node, bookmarks, lines, toc_start, toc_end
                )
            if len(child_nodes) < 2:
                child_nodes = extract_chapter_children(node, lines)
            node.children = child_nodes
        elif node.chapter_id == "financial_report_notes":
            node.children, node.line_end = locate_note_children(
                lines, node.line_start, node.line_end
            )

    chapters_json = [item.to_chapter().to_json() for item in all_top_level]
    output = {
        "report_file": report_file_value(md_path),
        "company": company,
        "ticker": ticker,
        "year": year,
        "index_version": 2,
        "chapters": chapters_json,
    }
    summary = {
        "source": "pdf_outline",
        "pdf_path": str(pdf_path),
        "md_path": str(md_path),
        "bookmark_count": len(outline),
        "found_top_level_chapters": [ch["title"] for ch in chapters_json],
        "missing_top_level_chapters": missing_top_level,
        "missing_financial_report_nodes": missing_financial,
    }
    return output, summary


def normalize_title_match(left: str, right: str) -> bool:
    a = normalize(strip_heading_prefix(left))
    b = normalize(strip_heading_prefix(right))
    if not a or not b:
        return False
    return a == b or a in b or b in a


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build annual-report section index from PDF bookmarks mapped to Markdown lines."
    )
    parser.add_argument("--pdf", type=Path, required=True, help="Source PDF (for bookmarks)")
    parser.add_argument("--md", type=Path, required=True, help="Converted Markdown report")
    parser.add_argument("--output", type=Path, help="Output .sections.json path")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    if not args.pdf.is_file():
        print(json.dumps({"error": f"PDF not found: {args.pdf}"}, ensure_ascii=False))
        return 1
    if not args.md.is_file():
        print(json.dumps({"error": f"Markdown not found: {args.md}"}, ensure_ascii=False))
        return 1

    _ensure_package("pymupdf")

    try:
        output_data, summary = build_index(args.pdf, args.md)
    except Exception as exc:  # noqa: BLE001 — surface as non-zero for skill fallback
        print(
            json.dumps(
                {"error": str(exc), "pdf": str(args.pdf), "md": str(args.md)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    output_path = args.output or default_output_path(args.md)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2 if args.pretty else None),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"output_path": str(output_path), "summary": summary},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
