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
    # Notes: many A-share reports use "合并财务报表项目注释" as the formal heading
    # rather than "合并财务报表附注". Tier 1: try the formal heading.
    # Tier 2: broad fallback to "公司基本情况" (some reports omit the notes heading entirely)
    ("合并财务报表附注", ["合并财务报表项目注释", "财务报表附注", "财务报表注释"],
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


def _heading_score(m: Match) -> int:
    """Score a matched line for heading likelihood (lower = more likely a real heading)."""
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


# ═══════════════════════════════════════════════════════════════════════════════
#  Auto command: one-shot end-to-end split without LLM-in-the-loop orchestration
# ═══════════════════════════════════════════════════════════════════════════════

# ── Regex patterns (NFKC-normalized before matching) ──

# TOC entry: chapter prefix + title + trailing dots/spaces + page number
# Matches: "第一节 ... 5", "第1章 ··· 10", "第一节重要提示.....2"
# Leader chars: . (U+002E), · (U+00B7), ． (U+FF0E), … (U+2026)
_TOC_ENTRY_RE = re.compile(
    r'第[一二三四五六七八九十百\d]+[节章].*?[.·．…\s]{2,}\s*\d+\s*$'
)

# TOC heading: "目录", "目 录", "目  录", "目 次" (NFKC-normalized before match)
_TOC_HEADING_RE = re.compile(r'^目\s{0,4}(录|次)$')

# Chapter-level markdown heading (## 第X节/第X章)
_CHAPTER_HEADING_RE = re.compile(r'^#{1,3}\s*第[一二三四五六七八九十百\d]+[节章]\s*\S')

# Extract section number from title
_SEC_NUM_RE = re.compile(r'第[一二三四五六七八九十百\d]+[节章]')

# TOC end boundary: "## Page X" or "备查文件目录" patterns
_TOC_BOUNDARY_RE = re.compile(r'^#{1,3}\s*Page\s+\d+|^备查文件目录')


def _is_toc_entry(line: str) -> bool:
    """Check if a line looks like a TOC entry (chapter + dots/leaders + page number)."""
    return bool(_TOC_ENTRY_RE.search(line))


def find_toc_range(file_path: str) -> tuple[int, int] | None:
    """
    Auto-detect the table of contents range in a financial report markdown.

    Robust against:
    - "目录" / "目 录" / "目  录" / table-format with CJK compat chars (⽬)
    - TOC entries with varying leader chars (dots, middle-dots, CJK dots, ellipsis)
    - TOC embedded in markdown tables (piped format)
    - TOC followed by "## Page X" or "备查文件目录" as natural boundary

    Algorithm:
    1. NFKC-normalize and find TOC heading via _TOC_HEADING_RE
    2. Scan forward collecting TOC entry lines
    3. Stop at first natural boundary ("## Page X" or "备查文件目录")

    Returns (first_entry_line, last_entry_line) or None if no TOC detected.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Find TOC heading (NFKC-normalized to handle CJK compat chars like ⽬→目)
    toc_heading = -1
    for i, line in enumerate(lines):
        cleaned = unicodedata.normalize('NFKC', line.strip())
        if _TOC_HEADING_RE.match(cleaned):
            toc_heading = i
            break

    if toc_heading < 0:
        return None

    # Scan forward for TOC entries (limit to 200 lines from heading)
    toc_start = -1
    toc_end = -1
    non_toc_count = 0
    search_end = min(toc_heading + 200, len(lines))

    for i in range(toc_heading + 1, search_end):
        raw = lines[i].strip()
        line_nfkc = unicodedata.normalize('NFKC', raw)

        # Check for natural TOC boundary
        if _TOC_BOUNDARY_RE.match(line_nfkc) and toc_start >= 0:
            break

        if _TOC_ENTRY_RE.search(line_nfkc):
            if toc_start < 0:
                toc_start = i
            toc_end = i
            non_toc_count = 0
        else:
            non_toc_count += 1
            # Blank lines and standalone page numbers between TOC entries are normal
            if raw == '' or re.match(r'^\d+$', raw):
                non_toc_count = 0
            # Single-line gaps in table-format TOC are normal too
            if re.match(r'^\|', raw):
                non_toc_count = 0
            # Stop after 6+ consecutive non-TOC, non-blank, non-page-num lines
            if non_toc_count >= 6 and toc_start >= 0:
                break

    if toc_start < 0:
        return None
    return (toc_start, toc_end)


def _toc_line_to_title(line: str) -> str | None:
    """
    Convert a TOC entry line to a cleaned chapter title.
    Returns None if the line doesn't contain a valid chapter heading.
    """
    cleaned = unicodedata.normalize('NFKC', line.strip())
    # Strip table pipes for table-format TOC
    cleaned = re.sub(r'^\|\s*', '', cleaned)
    cleaned = re.sub(r'\s*\|$', '', cleaned)
    # Only process lines with section numbers
    if not _SEC_NUM_RE.search(cleaned):
        return None
    title = normalize_title(cleaned)
    # Strip any remaining markdown heading prefix
    title = re.sub(r'^#{1,3}\s*', '', title)
    title = title.strip()
    if not title:
        return None
    return title


def extract_chapter_titles_from_toc(
    file_path: str, toc_start: int, toc_end: int
) -> tuple[list[str], list[str]]:
    """
    Extract top-level chapter titles from the TOC region.

    Returns (titles, skipped) where:
    - titles: successfully parsed chapter titles
    - skipped: raw TOC entry lines that didn't parse as chapters (for LLM review)
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    titles: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for i in range(toc_start, min(toc_end + 1, len(lines))):
        line = lines[i]
        line_nfkc = unicodedata.normalize('NFKC', line.strip())
        if not _TOC_ENTRY_RE.search(line_nfkc):
            continue
        title = _toc_line_to_title(line)
        if not title:
            skipped.append(line_nfkc[:120])
            continue
        if title in seen:
            continue
        if not _SEC_NUM_RE.search(title):
            skipped.append(f"[non-standard section number] {line_nfkc[:120]}")
            continue
        seen.add(title)
        titles.append(title)

    return titles, skipped


def _find_chapters_by_section_pattern(file_path: str) -> list[str]:
    """
    Fallback: find chapter sections when no traditional TOC is detected.

    Tries two strategies:
    1. ## 第X节/第X章 markdown headings (most common)
    2. Table-cell headings + single-line TOC extraction (rare, e.g. 002127)
    """
    titles: list[str] = []
    seen: set[str] = set()

    # Strategy 1: standard ## headings
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = unicodedata.normalize('NFKC', line.strip())
            if not _CHAPTER_HEADING_RE.match(stripped):
                continue
            title = normalize_title(stripped)
            title = re.sub(r'^#{1,3}\s*', '', title)
            title = title.strip()
            if title and title not in seen:
                seen.add(title)
                titles.append(title)

    if titles:
        return titles

    # Strategy 2: table-embedded content
    # 2a: Try to extract from single-line TOC first (most reliable for chapter names)
    #      Pattern: "02 第一节 标题... 06 第二节 标题..." all on one line
    _TABLE_TOC_RE = re.compile(
        r'\d{2,3}\s+第[一二三四五六七八九十百\d]+[节章]\s+\S.{2,30}?'
    )
    for line in open(file_path, 'r', encoding='utf-8'):
        stripped = unicodedata.normalize('NFKC', line.strip())
        # Look for TOC-like content in table cells (multiple numbered sections)
        toc_matches = _TABLE_TOC_RE.findall(stripped)
        if len(toc_matches) >= 5:  # Single line with 5+ sections = likely TOC
            for tm in toc_matches:
                # Remove leading page number: "02 第一节 标题" → "第一节 标题"
                title = re.sub(r'^\d+\s+', '', tm).strip()
                # Stop at English text boundary for cleaner names
                title = re.split(r'\s{2,}|[A-Z]{3,}', title)[0].strip()
                if title and title not in seen:
                    seen.add(title)
                    titles.append(title)

    # 2b: Extract from body heading lines (table cells containing chapter starts)
    #      Stop extraction at natural boundaries: English text, box-drawing chars,
    #      sub-section markers, or after a reasonable name length
    _TABLE_CHAPTER_RE = re.compile(
        r'^\|.*?第[一二三四五六七八九十百\d]+[节章]\s+\S'
    )
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = unicodedata.normalize('NFKC', line.strip())
            if not _TABLE_CHAPTER_RE.match(stripped):
                continue
            # Find the first chapter heading in this line, stop at delimiters
            m = re.search(r'(第[一二三四五六七八九十百\d]+[节章]\s+\S+?)(?:$|' +
                          r'(?=\s+(?:[A-Z]{2,}|[□☑]|' +
                          r'[一二三四五六七八九十\d]+[、,.．]|' +
                          r'公司董事会|股份有限公司|公司\b|本报告)))',
                          stripped)
            if not m:
                # Fallback: take the chapter prefix + next ~20 chars
                m = re.search(r'(第[一二三四五六七八九十百\d]+[节章]\s+\S.{0,18}?)(?:\s|$)', stripped)
            if not m:
                continue
            raw_title = m.group(1).strip()
            title = normalize_title(raw_title)
            title = title.strip()
            if title and title not in seen:
                seen.add(title)
                titles.append(title)

    # 2c: Deduplicate by section number — keep the longest title per section
    if titles:
        deduped: dict[str, str] = {}  # section_number → best_title
        for t in titles:
            sec_m = _SEC_NUM_RE.search(t)
            if not sec_m:
                continue
            sec = sec_m.group()
            if sec not in deduped or len(t) > len(deduped[sec]):
                deduped[sec] = t
        titles = list(deduped.values())

    return titles


def _disambiguate(matches: list[Match], prev_line: int, toc_end: int) -> Match:
    """
    Pick the best match from multiple candidates using rule-based scoring.

    Scoring priorities (in order):
    1. Has ## heading prefix (正文标题特征, strongest signal)
    2. Appears after the TOC region (not a TOC entry)
    3. Appears after the previous chapter (structural ordering)
    4. Closer to expected position (~500 lines from prev chapter)
    """
    def _score(m: Match) -> tuple[int, int, int, int]:
        s = m.line_text.strip()
        is_heading = 1 if re.match(r'^#{1,3}\s', s) else 0
        after_toc = 1 if m.line_num > toc_end else 0
        after_prev = 1 if m.line_num > prev_line else 0
        # Prefer matches closer to prev_line + expected chapter position (~500 lines)
        dist_penalty = abs(m.line_num - (prev_line + 500))
        return (is_heading, after_toc, after_prev, -dist_penalty)

    return max(matches, key=_score)


def resolve_chapter_lines(
    file_path: str, chapters: list[str], toc_end: int
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """
    Find the line number for each chapter in the file body.

    Uses fuzzy_find with auto-disambiguation for multiple candidates,
    and tiered fallback for zero candidates.

    Returns (resolved, unresolved) where:
    - resolved: list of (line_number, chapter_name) sorted by line number
    - unresolved: list of (original_index, chapter_name) — needs AI intervention
    """
    resolved: list[tuple[int, str]] = []
    unresolved: list[tuple[int, str]] = []
    prev_line = 0

    for i, ch in enumerate(chapters):
        matches = _find_chapter_line(file_path, ch, toc_end, i == 0, prev_line)

        if len(matches) == 1:
            resolved.append((matches[0].line_num, ch))
            prev_line = matches[0].line_num
        elif len(matches) > 1:
            best = _disambiguate(matches, prev_line, toc_end)
            resolved.append((best.line_num, ch))
            prev_line = best.line_num
        else:
            unresolved.append((i, ch))

    return resolved, unresolved


def _find_chapter_line(
    file_path: str, ch: str, toc_end: int, is_first: bool, prev_line: int
) -> list[Match]:
    """
    Find body-line candidates for a chapter title. Multi-tier fallback:

    Tier 1: fuzzy_find with TOC exclusion (or without for first chapter, since
            the first chapter heading may appear BEFORE the TOC region)
    Tier 2: for non-first chapters with zero matches, retry without TOC exclusion
            (some reports have the chapter heading also appear in TOC region)
    Tier 3: section-number-only fallback (e.g. search for "第五节" instead of full title)
    """
    # Tier 1: standard search
    exclude = 0 if is_first else toc_end
    matches = fuzzy_find(file_path, ch, exclude_before=exclude)

    # For first chapter: filter out TOC entries, keep body headings
    if is_first:
        # Separate matches into body (before/at TOC) and TOC entries
        body_matches = [m for m in matches if not _is_toc_entry(m.line_text)]
        # Also check for the chapter appearing in a short markdown heading form
        # (e.g. "第一节 重要提示" as ## heading very early in the file)
        if not body_matches:
            body_matches = matches  # fallback: use all matches
        # Prefer early matches (before or at the start of the TOC area) for chapter 1
        matches = sorted(body_matches, key=lambda m: m.line_num)
    elif len(matches) > 1:
        # For non-first chapters: filter out obvious TOC entries
        matches = [m for m in matches if not _is_toc_entry(m.line_text)]

    # Tier 2: no-exclusion search for chapters that got zero matches
    if not matches and not is_first:
        matches = fuzzy_find(file_path, ch, exclude_before=0)
        # Keep only body headings (after TOC or with ## prefix)
        matches = [m for m in matches
                   if m.line_num > toc_end or _is_heading_line(m.line_text)]
    elif not matches and is_first:
        # For first chapter with zero matches from full title: try searching
        # within first 100 lines only (removes TOC noise)
        # Already searched without exclusion, but try broader
        pass

    # Tier 3: section-number-only fallback
    if not matches:
        sec_match = _SEC_NUM_RE.search(ch)
        if sec_match:
            sec_num = sec_match.group()
            matches = fuzzy_find(file_path, sec_num, exclude_before=0)
            if is_first:
                matches = [m for m in matches if not _is_toc_entry(m.line_text)]
            elif len(matches) > 1:
                matches = [m for m in matches
                           if m.line_num > toc_end or _is_heading_line(m.line_text)]

    # Ensure matches are in line order
    matches.sort(key=lambda m: m.line_num)
    return matches


def _is_heading_line(line: str) -> bool:
    """Check if a line looks like a section heading (## prefix or short standalone)."""
    s = line.strip()
    return bool(re.match(r'^#{1,3}\s', s)) or (len(s) < 30 and _SEC_NUM_RE.search(s))


def _is_financial_report_chapter(name: str) -> bool:
    """Check if a chapter name indicates it's the financial report section."""
    return '财务报告' in name


# ═══════════════════════════════════════════════════════════════════════════════
#  Context-printing helpers: output actual file content so LLM can decide
#  without extra run_command calls to inspect the file.
# ═══════════════════════════════════════════════════════════════════════════════

def _print_file_sample(file_path: str, num_lines: int = 100) -> None:
    """Print first N lines of the file so LLM can identify document structure."""
    print(f"\n── File sample (first {num_lines} lines of {file_path}) ──")
    with open(file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i >= num_lines:
                break
            stripped = line.rstrip()
            if stripped:
                print(f"  [{i + 1}] {stripped[:150]}")


def _print_unresolved_context(
    file_path: str,
    chapter_name: str,
    chapter_index: int,
    search_start: int,
    search_end: int,
    all_lines: list[str],
) -> None:
    """
    Print enough file content around the search range for an LLM to identify
    the chapter heading without needing additional run_command calls.

    Shows:
    - Lines around the midpoint of the search range
    - Any lines matching the chapter's section number pattern in the range
    - A ready-to-use split command template
    """
    total = len(all_lines)

    # ── Context around range midpoint ──
    mid = (search_start + search_end) // 2
    ctx_start = max(search_start, mid - 12)
    ctx_end = min(search_end, mid + 12)

    print(f"\n{'─' * 60}")
    print(f"UNRESOLVED: [{chapter_index + 1}] {chapter_name}")
    print(f"Search range: lines {search_start}–{search_end}")
    print(f"\nContext around line {mid}:")
    for i in range(ctx_start - 1, ctx_end):
        if i < 0 or i >= total:
            continue
        marker = ">>>" if (i + 1) == mid else "   "
        print(f"  {marker} [{i + 1}] {all_lines[i].rstrip()[:150]}")

    # ── Section-number matches in the search range ──
    sec_m = _SEC_NUM_RE.search(chapter_name)
    if sec_m:
        sec_num = sec_m.group()
        matches_in_range: list[tuple[int, str]] = []
        for i in range(max(0, search_start - 1), min(total, search_end)):
            if sec_num in all_lines[i]:
                matches_in_range.append((i + 1, all_lines[i].rstrip()[:150]))

        if matches_in_range:
            print(f"\nLines containing '{sec_num}' in range:")
            for ln, text in matches_in_range[:15]:
                print(f"  [{ln}] {text}")
        else:
            print(f"\nNo lines matching '{sec_num}' found in range — try broader search.")

    # ── LLM action hint ──
    print(f"\n→ LLM: review the context above, identify the chapter heading line number,")
    print(f"  then add it with:")
    print(f"  printf '{chapter_index + 1}<TAB>{chapter_name}\\n' >> /tmp/chapters_fixed.txt")
    print(f"  (collect all fixes, then re-run: python3 split_report.py split <file> <output> < /tmp/chapters_fixed.txt)")
    print(f"{'─' * 60}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Financial sub-section auto-split (with context output for ambiguous cases)
# ═══════════════════════════════════════════════════════════════════════════════

def _run_financial_sub(file_path: str, output_dir: str) -> int:
    """
    Run financial sub-section splitting on a financial report chapter.

    Auto-accepts single-candidate sections AND sections where the top candidate
    has a clear score advantage (## heading or numbered vs. body text).

    For ambiguous candidates, prints surrounding context so the LLM can decide
    without extra run_command calls.

    Returns 0 on success, 1 on partial (some sections need LLM review).
    """
    results = find_sub_sections(file_path)

    # Read file lines for context printing
    with open(file_path, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()

    positions: list[int] = []
    names: list[str] = []
    ambiguous: list[tuple[str, list[Match]]] = []

    for section_key, matches in results:
        if not matches:
            ambiguous.append((section_key, matches))
            continue
        if len(matches) == 1:
            positions.append(matches[0].line_num)
            names.append(section_key)
        else:
            s1 = _heading_score(matches[0])
            s2 = _heading_score(matches[1])
            if s1 <= 1:
                positions.append(matches[0].line_num)
                names.append(section_key)
            elif s1 == 2 and s2 >= 4:
                positions.append(matches[0].line_num)
                names.append(section_key)
            else:
                ambiguous.append((section_key, matches))

    if ambiguous:
        # Auto-split what we can
        if positions:
            split_results = split_at_lines(file_path, positions, names, output_dir)
            for name, start, end, fname in split_results:
                print(f"  [auto] {name}: lines {start}-{end} → {fname}")

        print(f"\n{'─' * 60}")
        print(f"Financial sub-sections — {len(ambiguous)} need LLM review")
        print(f"File: {file_path}")

        for section_key, matches in ambiguous:
            print(f"\n── [{section_key}] ──")
            if not matches:
                print(f"  Zero candidates. Try broader keyword search or find manually.")
                continue

            print(f"  Top candidates ({len(matches)} total):")
            for rank, m in enumerate(matches[:5]):
                ln = m.line_num
                score = _heading_score(m)
                print(f"  #{rank + 1} line {ln} (score={score}): {m.line_text[:100]}")

                # Print ±3 lines of context around each candidate
                ctx_s = max(0, ln - 4)
                ctx_e = min(len(all_lines), ln + 4)
                for ci in range(ctx_s, ctx_e):
                    prefix = ">>>" if ci + 1 == ln else "   "
                    print(f"      {prefix} [{ci + 1}] {all_lines[ci].rstrip()[:120]}")

        print(f"\n→ LLM: confirm the correct line for each ambiguous section above,")
        print(f"  then pipe to: python3 split_report.py split {file_path} {output_dir}")
        return 1

    # All resolved → auto-split
    split_results = split_at_lines(file_path, positions, names, output_dir)
    for name, start, end, fname in split_results:
        print(f"  {name}: lines {start}-{end} → {fname}")

    for name, start, end, fname in split_results:
        if end - start < 5:
            print(f"  WARNING: '{fname}' is very small ({end - start} lines) — may be incorrect",
                  file=sys.stderr)

    return 0


# ═══════════════════════════════════════════════════════════════════════════════
#  auto command — mechanical work + context output for LLM-targeted fixes
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_auto(args):
    """
    One-shot end-to-end split: TOC → extract → resolve → cut → optional financial-sub.

    Philosophy: script does 90% of the mechanical work in one call. When it can't
    resolve something, it outputs the actual file content (surrounding lines) so the
    LLM can make an informed decision WITHOUT extra run_command calls to inspect the file.

    Exit codes:
      0 — complete success, no LLM needed
      1 — partial success: main split done, some chapters or financial-sub need LLM review
      2 — no split possible: TOC not found or no chapters resolved; LLM must read file
    """
    file_path = args.file
    output_dir = args.output_dir

    if not os.path.exists(file_path):
        print(f"ERROR: file not found: {file_path}", file=sys.stderr)
        sys.exit(2)

    total_lines = sum(1 for _ in open(file_path, 'r', encoding='utf-8'))
    all_lines: list[str] = []

    # ── Step 1: Find TOC ──
    need_llm = False  # accumulates: TOC gaps, unresolved chapters, etc.
    toc_range = find_toc_range(file_path)
    if toc_range is None:
        chapters = _find_chapters_by_section_pattern(file_path)
        if chapters:
            print("(no traditional TOC found; using section-heading scan)", file=sys.stderr)
            toc_end = 0
        else:
            # Can't find chapters at all — print file sample for LLM
            print("ERROR: Cannot detect TOC or chapter headings.", file=sys.stderr)
            _print_file_sample(file_path, 100)
            print("\n→ LLM: review the file sample above to understand the document format.",
                  file=sys.stderr)
            print("  Use grep to find chapter headings, then build split input manually.", file=sys.stderr)
            sys.exit(2)
    else:
        toc_start, toc_end = toc_range
        print(f"TOC: lines {toc_start}–{toc_end}")
        chapters, toc_skipped = extract_chapter_titles_from_toc(file_path, toc_start, toc_end)
        if toc_skipped:
            print(f"  ⚠ {len(toc_skipped)} TOC entries could not be parsed as chapters:", file=sys.stderr)
            for s in toc_skipped[:10]:
                print(f"    → {s}", file=sys.stderr)
            print(f"  → LLM: review these entries — they may need manual chapter definition.", file=sys.stderr)

        # Quality check: count ALL TOC-like lines (broad match) vs. extracted chapters
        # Catches non-standard section numbering like "Part5", "Section V", etc.
        _BROAD_TOC_RE = re.compile(r'.+[.·．…\s]{3,}\s*\d+\s*$')
        with open(file_path, 'r', encoding='utf-8') as _f:
            _toc_lines = _f.readlines()[toc_start:toc_end + 1]
        broad_toc_count = sum(1 for l in _toc_lines
                              if _BROAD_TOC_RE.search(unicodedata.normalize('NFKC', l.strip())))
        if broad_toc_count > len(chapters):
            print(f"\n  ⚠ TOC has ~{broad_toc_count} entries but only {len(chapters)} parsed as chapters.",
                  file=sys.stderr)
            print(f"  → LLM: the TOC contains non-standard section numbering.", file=sys.stderr)
            print(f"  → TOC region (✓=parsed, ?=unrecognized):", file=sys.stderr)
            for i, l in enumerate(_toc_lines):
                stripped = unicodedata.normalize('NFKC', l.strip())
                if stripped and not stripped.isdigit():
                    marker = "✓" if _TOC_ENTRY_RE.search(stripped) else "?"
                    print(f"    {marker} [{toc_start + i + 1}] {stripped[:130]}", file=sys.stderr)
            need_llm = True

    if not chapters:
        print("ERROR: No chapter titles found.", file=sys.stderr)
        _print_file_sample(file_path, 100)
        print("\n→ LLM: review the file sample above.", file=sys.stderr)
        sys.exit(2)

    # Deduplicate by section number
    _deduped: dict[str, str] = {}
    _sec_order: dict[str, int] = {}
    for i, ch in enumerate(chapters):
        sec_m = _SEC_NUM_RE.search(ch)
        if sec_m:
            sec = sec_m.group()
            if sec not in _sec_order:
                _sec_order[sec] = i
            if sec not in _deduped or len(ch) > len(_deduped[sec]):
                _deduped[sec] = ch
    if len(_deduped) < len(chapters):
        chapters = sorted(_deduped.values(),
                          key=lambda c: _sec_order.get(
                              _SEC_NUM_RE.search(c).group() if _SEC_NUM_RE.search(c) else '', 999))

    print(f"Chapters: {len(chapters)}")

    # ── Step 2: Resolve chapter lines ──
    resolved, unresolved = resolve_chapter_lines(file_path, chapters, toc_end)
    need_llm = need_llm or bool(unresolved)

    # Detect TOC extraction gaps: chapters dropped during parsing or resolution
    if not unresolved and len(resolved) < len(chapters):
        # Some chapters were in TOC but couldn't be resolved — find which ones
        resolved_names = {n for _, n in resolved}
        missing_from_resolve = [c for c in chapters if c not in resolved_names]
        if missing_from_resolve:
            print(f"\n  ⚠ {len(missing_from_resolve)} chapter(s) from TOC could not be located in file body:",
                  file=sys.stderr)
            for c in missing_from_resolve:
                print(f"    → '{c}'", file=sys.stderr)
            print(f"  → LLM: these chapters may use non-standard headings. Use grep to locate them.",
                  file=sys.stderr)
            need_llm = True
            for c in missing_from_resolve:
                idx = chapters.index(c)
                if (idx, c) not in unresolved:
                    unresolved.append((idx, c))

    if not resolved:
        print("ERROR: Could not resolve any chapter line numbers.", file=sys.stderr)
        _print_file_sample(file_path, 100)
        print("\n→ LLM: review the file sample above. Search for chapter headings with grep,", file=sys.stderr)
        print("  then pipe to: python3 split_report.py split <file> <output>", file=sys.stderr)
        sys.exit(2)

    # ── Step 3: Split what we can ──
    resolved.sort(key=lambda x: x[0])
    resolved_map: dict[str, int] = {n: p for p, n in resolved}

    print(f"Cutting {len(resolved)}/{len(chapters)} chapters...")
    line_nums = [p for p, _ in resolved]
    ch_names = [n for _, n in resolved]
    results = split_at_lines(file_path, line_nums, ch_names, output_dir)

    for name, start, end, fname in results:
        print(f"  {name}: lines {start}-{end} → {fname}")

    # ── Step 4: Print context for unresolved chapters ──
    if unresolved:
        # Lazy-load file lines (only needed when there are unresolved chapters)
        with open(file_path, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()

        for idx, ch in unresolved:
            # Compute search range from adjacent resolved chapters
            search_start = 1
            search_end = total_lines
            for r_name, r_line in resolved_map.items():
                r_idx = chapters.index(r_name) if r_name in chapters else -1
                if r_idx >= 0 and r_idx < idx:
                    search_start = r_line
            for r_name, r_line in resolved_map.items():
                r_idx = chapters.index(r_name) if r_name in chapters else -1
                if r_idx >= 0 and r_idx > idx:
                    search_end = r_line
                    break

            _print_unresolved_context(
                file_path, ch, idx, search_start, search_end, all_lines
            )

    # ── Step 5: Optional financial-sub ──
    finsub_need_llm = False
    if args.financial_sub:
        last_chapter = results[-1]
        if _is_financial_report_chapter(last_chapter[0]):
            last_file = os.path.join(output_dir, last_chapter[3])
            print(f"\n── financial-sub on: {os.path.basename(last_file)} ──")
            rc = _run_financial_sub(last_file, output_dir)
            if rc != 0:
                finsub_need_llm = True
        else:
            print(f"\nLast chapter '{last_chapter[0]}' — not 财务报告, skipping --financial-sub.",
                  file=sys.stderr)

    # ── Final status ──
    if need_llm or finsub_need_llm:
        print(f"\n{'=' * 60}")
        print("PARTIAL SUCCESS — LLM review needed for items flagged above.")
        print(f"  Resolved chapters: {len(resolved)}/{len(chapters)}")
        print(f"  Unresolved: {[f'[{i+1}]{ch}' for i, ch in unresolved]}")
        if finsub_need_llm:
            print(f"  Financial-sub: needs LLM confirmation")
        print(f"{'=' * 60}")
        sys.exit(1)

    print("\nAll done. ✓")


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

    p_auto = sub.add_parser("auto", help="One-shot end-to-end: find TOC → extract → split → verify")
    p_auto.add_argument("file", help="Markdown file path")
    p_auto.add_argument("output_dir", help="Output directory for split files")
    p_auto.add_argument(
        "--financial-sub", action="store_true",
        help="Auto-run financial sub-section splitting if last chapter is 财务报告"
    )
    p_auto.set_defaults(func=cmd_auto)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
    else:
        args.func(args)


if __name__ == "__main__":
    main()
