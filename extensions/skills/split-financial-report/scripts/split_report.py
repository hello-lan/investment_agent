#!/usr/bin/env python3
"""Utilities for splitting markdown financial reports by chapter headings."""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

# PDF conversion noise characters to strip
PDF_NOISE = re.compile(r"[​­‌‍﻿ 　]")


def normalize_title(title: str) -> str:
    """Clean a TOC chapter entry: strip trailing dots, page numbers, noise."""
    cleaned = PDF_NOISE.sub("", title)
    # Remove trailing dots + page numbers: "...... 2" or ".... 42"
    cleaned = re.sub(r"[.\s]+\d+\s*$", "", cleaned)
    # Remove any remaining trailing dots/spaces
    cleaned = re.sub(r"[.\s]+$", "", cleaned)
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
    # Allow optional markdown heading prefix (##, ###, etc.) and table-cell pipes
    return r"^\s*(?:#{1,3}\s*)?\|?\s*" + body + r"\s*\|?\s*$"


class Match(NamedTuple):
    line_num: int
    line_text: str


def fuzzy_find(file_path: str, chapter_title: str, exclude_before: int = 0) -> list[Match]:
    """
    Find all lines that match the fuzzy regex for chapter_title.
    Returns list of (line_number, line_text).
    """
    pattern = build_fuzzy_regex(chapter_title)
    if not pattern:
        return []

    regex = re.compile(pattern)
    matches: list[Match] = []

    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i <= exclude_before:
                continue
            stripped = line.strip()
            if regex.match(stripped):
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

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
    else:
        args.func(args)


if __name__ == "__main__":
    main()
