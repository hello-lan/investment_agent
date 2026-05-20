#!/usr/bin/env python3
"""Utilities for splitting markdown financial reports by chapter headings."""

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import NamedTuple

# PDF conversion noise characters to strip
PDF_NOISE = re.compile(r"[​­‌‍﻿ 　]")

# Financial sub-report sections to extract (order matters for split ranges)
# Each entry: (section_key, primary_titles, filter_words, fallback_titles, broad_titles)
# Tried in order: primary → fallback → broad (Tier 1 fallback)
# broad_titles use wider keywords; _is_parent_section() filters parent-company matches
FINANCIAL_SUB_SECTIONS = [
    # Audit report: prefer "一、审计报告" heading; filter inline mentions
    ("审计报告", ["一、审计报告", "审计报告"],
     ["详见", "参见", "参阅", "见本", "正文", "签署日期", "审计报告文号", "审计报告日",
      "注册会计师对财务报表审计的责任", "形成审计意见", "其他信息", "关键审计事项",
      "内部控制审计报告", "内控审计报告", "内部控制自我评价", "非标准审计报告",
      "内部控制鉴证报告", "审计报告相关", "审计报告的出具"],
     [], []),
    # Consolidated statements: filter sub-section notes
    ("合并资产负债表", ["合并资产负债表"], ["项目注释"], [],
     ["资产负债表"]),
    ("合并利润表", ["合并利润表"], ["项目注释"], [],
     ["利润表"]),
    ("合并现金流量表", ["合并现金流量表"], ["项目注释"], [],
     ["现金流量表"]),
    ("合并所有者权益变动表", ["合并所有者权益变动表", "合并股东权益变动表"], ["项目注释"], [],
     ["所有者权益变动表", "股东权益变动表"]),
    # Notes: broad = 公司基本情况 (reports sometimes omit "财务报表附注" heading entirely)
    ("合并财务报表附注", ["财务报表附注", "财务报表注释"],
     ["详见", "参见", "参阅", "见本", "以及相关", "情况详见", "及相关财务", "。"],
     [],
     ["公司基本情况"]),
]

# Keywords that indicate parent-company statements (to be skipped after cleaning)
_PARENT_KEYWORDS = [
    "母公司资产负债表", "母公司利润表", "母公司现金流量表",
    "母公司所有者权益变动表", "母公司股东权益变动表",
    "公司资产负债表", "公司利润表", "公司现金流量表",
    "公司所有者权益变动表", "公司股东权益变动表",
]


def normalize_title(title: str) -> str:
    """Clean a TOC chapter entry: strip trailing dots, page numbers, noise."""
    cleaned = unicodedata.normalize("NFKC", title)
    cleaned = PDF_NOISE.sub("", cleaned)
    # Remove trailing dots + page numbers: "...... 2" or ".... 42"
    # Remove trailing dots + page numbers: "...... 2" or "···· 42"
    # Includes U+002E (.), U+00B7 (·), U+FF0E (．)
    cleaned = re.sub(r"[.·．\s]+\d+\s*$", "", cleaned)
    # Remove any remaining trailing dots/spaces
    cleaned = re.sub(r"[.·．\s]+$", "", cleaned)
    return cleaned.strip()


def build_fuzzy_regex(title: str) -> str:
    """
    Build a fuzzy regex that matches the title regardless of whitespace
    inserted between characters (common PDF→markdown artifact).

    Example: "第一节 公司治理" → '^\\s*第\\s*一\\s*节\\s*公\\s*司\\s*治\\s*理\\s*$'
    """
    # Strip PDF noise and whitespace from the title itself
    cleaned = PDF_NOISE.sub("", title)
    cleaned = re.sub(r"\s+", "", cleaned)
    if not cleaned:
        return ""

    # Escape each character and join with \s*
    chars = [re.escape(c) for c in cleaned]
    body = r"\s*".join(chars)
    # Allow optional markdown heading prefix (##, ###, etc.), table-cell pipes,
    # company name prefix, and page number suffix (e.g. "招商银行 第一章 标题 11")
    return r"(?:#{1,3}\s*)?\|?\s*" + body + r"\s*\|?\s*"


class Match(NamedTuple):
    line_num: int
    line_text: str


def fuzzy_find(file_path: str, chapter_title: str, exclude_before: int = 0) -> list[Match]:
    """
    Find all lines that match the fuzzy regex for chapter_title.
    Returns list of (line_number, line_text).
    """
    # Normalize the search title to handle CJK compatibility variants (e.g. ⾦→金)
    normalized_title = unicodedata.normalize("NFKC", chapter_title)
    pattern = build_fuzzy_regex(normalized_title)
    if not pattern:
        return []

    regex = re.compile(pattern)
    matches: list[Match] = []

    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i <= exclude_before:
                continue
            # Normalize the line to handle CJK compatibility variants
            stripped = unicodedata.normalize("NFKC", line.strip())
            if regex.search(stripped):
                matches.append(Match(i, stripped))

    return matches


def split_at_lines(
    file_path: str,
    line_positions: list[int],
    chapter_names: list[str],
    output_dir: str,
) -> list[tuple[str, int, int, str]]:
    """
    Split file at given line positions (1-indexed).

    Returns list of (chapter_name, start_line, end_line, output_filename).
    """
    os.makedirs(output_dir, exist_ok=True)
    stem = Path(file_path).stem

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    total_lines = len(lines)
    results: list[tuple[str, int, int, str]] = []

    for i, (start_line, name) in enumerate(zip(line_positions, chapter_names)):
        end_line = line_positions[i + 1] if i + 1 < len(line_positions) else total_lines + 1

        safe_name = re.sub(r"[^\w一-鿿]", "_", name)
        safe_name = re.sub(r"_+", "_", safe_name).strip("_")

        filename = f"{stem}_ch{i + 1:02d}_{safe_name}.md"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines[start_line - 1 : end_line - 1])

        results.append((name, start_line, end_line - 1, filename))

    return results


def _is_parent_section(title: str) -> bool:
    """Check if a matched line is a parent-company section to be skipped."""
    cleaned = unicodedata.normalize("NFKC", title)
    cleaned = PDF_NOISE.sub("", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    if "合并" in cleaned:
        return False  # consolidated statement, keep it
    return any(kw in cleaned for kw in _PARENT_KEYWORDS)


def find_sub_sections(file_path: str) -> list[tuple[str, list[Match]]]:
    """
    Search for all financial sub-section headings.
    Returns list of (section_key, [Match, ...]) excluding parent-company matches.
    """
    results: list[tuple[str, list[Match]]] = []

    for entry in FINANCIAL_SUB_SECTIONS:
        section_key, search_titles, filter_words, fallback_titles, broad_titles = entry

        # Search primary titles first
        all_matches = _search_titles(file_path, search_titles, filter_words)

        # If no matches, try fallback titles
        if not all_matches and fallback_titles:
            all_matches = _search_titles(file_path, fallback_titles, filter_words)

        # Tier 1 fallback: try broad titles (wider keywords, _is_parent_section filters parent)
        if not all_matches and broad_titles:
            all_matches = _search_titles(file_path, broad_titles, filter_words)

        # Dedupe by line number
        seen: set[int] = set()
        unique: list[Match] = []
        for m in all_matches:
            if m.line_num not in seen:
                seen.add(m.line_num)
                unique.append(m)
        # Sort by heading likelihood: ## heading with numbered prefix > ## heading
        # > plain numbered prefix > short > medium > long
        def _heading_score(m: Match) -> int:
            s = m.line_text.strip()
            is_heading = bool(re.match(r'^#{1,3}\s', s))
            has_numbered = bool(re.match(r'[一二三四五六七八九十\d]+[、.．]', s))
            if is_heading and has_numbered:
                return 0  # Best: ## heading with numbered prefix (e.g. ## 一、审计报告)
            if is_heading and len(s) < 30:
                return 1  # Good: short ## heading
            if has_numbered and len(s) < 30:
                return 2  # OK: numbered prefix, short (might be TOC entry)
            if is_heading:
                return 3  # ## heading, longer
            if len(s) < 20:
                return 4  # Short line, no ## prefix
            if len(s) < 50:
                return 5  # Medium line
            return 6  # Long line (likely body text)
        unique.sort(key=lambda m: (_heading_score(m), m.line_num))
        results.append((section_key, unique))
    return results


def _compute_missing_ranges(
    results: list[tuple[str, list[Match]]],
    total_lines: int,
) -> list[tuple[str, int, int, str, str]]:
    """
    For sections with 0 candidates, compute the line range where the heading
    should be searched, bounded by neighboring found sections.

    Returns [(section_key, start_line, end_line, prev_key, next_key), ...]
    - start_line: heading line of previous found section (or 1)
    - end_line: heading line of next found section (or total_lines)
    - prev_key / next_key: names of bounding sections (for diagnostic messages)
    - Consecutive missing sections share the same range.
    """
    if not results:
        return []

    total = len(results)
    missing: list[tuple[str, int, int, str, str]] = []

    for i, (key, matches) in enumerate(results):
        if matches:
            continue  # has candidates, skip

        # Find previous found section
        prev_start = 1
        prev_key = "(start of file)"
        for j in range(i - 1, -1, -1):
            if results[j][1]:
                prev_start = results[j][1][0].line_num
                prev_key = results[j][0]
                break

        # Find next found section
        next_start = total_lines
        next_key = "(end of file)"
        for j in range(i + 1, total):
            if results[j][1]:
                next_start = results[j][1][0].line_num
                next_key = results[j][0]
                break

        missing.append((key, prev_start, next_start, prev_key, next_key))

    return missing


def _search_titles(file_path: str, titles: list[str], filter_words: list[str]) -> list[Match]:
    """Search for multiple titles and return filtered, deduplicated matches."""
    all_matches: list[Match] = []
    for title in titles:
        matches = fuzzy_find(file_path, title)
        filtered = [
            m for m in matches
            if not _is_parent_section(m.line_text)
            and not any(fw in m.line_text for fw in filter_words)
        ]
        all_matches.extend(filtered)
    return all_matches


# ---- CLI ----
def cmd_find(args):
    """grep-like: find fuzzy matches for a title, print line_num:line_text"""
    results = fuzzy_find(args.file, args.title, exclude_before=args.exclude_before)
    for m in results:
        print(f"{m.line_num}:{m.line_text}")


def cmd_split(args):
    """Split a file. Input via stdin: each line is 'line_num<tab>chapter_name'."""
    input_text = sys.stdin.read().strip()
    if not input_text:
        print("Error: no input provided via stdin", file=sys.stderr)
        sys.exit(1)

    line_positions: list[int] = []
    chapter_names: list[str] = []
    for line in input_text.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            line_positions.append(int(parts[0]))
            chapter_names.append(parts[1].strip())
        else:
            line_positions.append(int(parts[0]))
            chapter_names.append(f"chapter_{len(line_positions)}")

    results = split_at_lines(args.file, line_positions, chapter_names, args.output_dir)
    for name, start, end, fname in results:
        print(f"{name}\tlines {start}-{end}\t{fname}")


def cmd_financial_sub(args):
    """Discover financial sub-sections and optionally auto-split."""
    results = find_sub_sections(args.file)
    has_ambiguity = any(len(m) != 1 for _, m in results)
    missing = [k for k, m in results if not m]

    # Count total lines for range computation
    with open(args.file, "r", encoding="utf-8") as f:
        total_lines = sum(1 for _ in f)

    # Compute search ranges for missing sections
    missing_ranges = _compute_missing_ranges(results, total_lines)
    range_map: dict[str, tuple[int, int, str, str]] = {
        key: (start, end, pk, nk) for key, start, end, pk, nk in missing_ranges
    }

    for section_key, matches in results:
        print(f"\n[{section_key}] ({len(matches)} candidates):")
        for m in matches:
            print(f"  {m.line_num}: {m.line_text[:100]}")
        if not matches and section_key in range_map:
            start, end, pk, nk = range_map[section_key]
            print(f"  ! Search range: lines {start}-{end} (between {pk} and {nk})")

    if missing:
        print(f"\nWarning: no candidates for: {', '.join(missing)}", file=sys.stderr)

    if args.stdin_split:
        if missing:
            # Partial success: print confirmed + missing with ranges
            print("\n--- Partial results (sections marked ? need AI to locate) ---")
            for section_key, matches in results:
                if matches:
                    print(f"{matches[0].line_num}\t{section_key}")
                else:
                    start, end, pk, nk = range_map[section_key]
                    print(f"?\t{section_key}  # range: lines {start}-{end} ({pk} → {nk})")
            print("\nComplete the missing ? entries above, then pipe all lines to:")
            print(f"  python3 split_report.py split {args.file} {args.output_dir}")
            sys.exit(2)

        line_positions = [matches[0].line_num for _, matches in results]
        chapter_names = [section_key for section_key, _ in results]
        split_results = split_at_lines(args.file, line_positions, chapter_names, args.output_dir)
        for name, start, end, fname in split_results:
            print(f"{name}\tlines {start}-{end}\t{fname}")
        return

    # Interactive mode: print split-ready selection or hint
    print("\n--- Candidate selection (first-ranked per section) ---")
    for section_key, matches in results:
        if matches:
            marker = " *" if len(matches) > 1 else ""
            print(f"{matches[0].line_num}\t{section_key}{marker}")
        elif section_key in range_map:
            start, end, pk, nk = range_map[section_key]
            print(f"?\t{section_key}  # range: lines {start}-{end} ({pk} → {nk})")
    if has_ambiguity:
        print("\nSections marked * have multiple candidates. Review above, then pipe chosen lines to:")
        print("  python3 split_report.py split <file> <out_dir>")
        print("Or re-run with --stdin-split to auto-accept first-ranked candidates.")
    if missing:
        print("\nSections marked ? have no candidates — use the listed search ranges for AI-assisted location.")


def main():
    parser = argparse.ArgumentParser(description="Split markdown financial reports")
    sub = parser.add_subparsers(dest="command")

    p_find = sub.add_parser("find", help="Fuzzy-find chapter heading locations")
    p_find.add_argument("file", help="Markdown file path")
    p_find.add_argument("title", help="Chapter title to search for")
    p_find.add_argument(
        "--exclude-before", type=int, default=0,
        help="Ignore lines before this line number (for excluding TOC region)"
    )
    p_find.set_defaults(func=cmd_find)

    p_split = sub.add_parser("split", help="Split file at given line numbers")
    p_split.add_argument("file", help="Markdown file path")
    p_split.add_argument("output_dir", help="Output directory for split files")
    p_split.set_defaults(func=cmd_split)

    p_norm = sub.add_parser("normalize", help="Normalize a chapter title from TOC")
    p_norm.add_argument("title", help="Raw TOC line")
    p_norm.set_defaults(func=lambda a: print(normalize_title(a.title)))

    p_finsub = sub.add_parser("financial-sub", help="Find financial sub-sections in a report chapter")
    p_finsub.add_argument("file", help="Financial report markdown file (the last chapter)")
    p_finsub.add_argument("output_dir", help="Output directory for split sub-files")
    p_finsub.add_argument(
        "--stdin-split", action="store_true",
        help="Auto-split: take first candidate for each section and split"
    )
    p_finsub.set_defaults(func=cmd_financial_sub)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
    else:
        args.func(args)


if __name__ == "__main__":
    main()
