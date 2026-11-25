#!/usr/bin/env python3
"""Merge missing chapters / empty children from an MD-fallback index into a primary index."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from index_common import fix_top_level_ranges, semantic_key_for_chapter


ALLOWED_CHILD_PARENT_KEYS = {"profile", "mda", "financial_report_notes"}


def _load_index(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"index root must be object: {path}")
    chapters = data.get("chapters")
    if not isinstance(chapters, list):
        raise ValueError(f"chapters must be a list: {path}")
    return data


def _valid_range(chapter: dict) -> bool:
    start = chapter.get("line_start")
    end = chapter.get("line_end")
    return isinstance(start, int) and isinstance(end, int) and start > 0 and start <= end


def _parent_allows_children(chapter: dict) -> bool:
    key = semantic_key_for_chapter(chapter)
    if key in ALLOWED_CHILD_PARENT_KEYS:
        return True
    chapter_id = str(chapter.get("chapter_id") or "")
    return chapter_id in {"chapter_02", "chapter_03", "financial_report_notes"}


def _clip_children_to_parent(parent: dict, children: list) -> list[dict]:
    line_start = int(parent.get("line_start") or 0)
    line_end = int(parent.get("line_end") or line_start)
    kept: list[dict] = []
    for child in children:
        if not isinstance(child, dict) or not _valid_range(child):
            continue
        child_start = int(child["line_start"])
        child_end = int(child["line_end"])
        if child_start < line_start or child_start > line_end:
            continue
        clipped = dict(child)
        clipped["line_end"] = min(max(child_start, child_end), line_end)
        clipped.pop("children", None)  # never introduce a third level
        kept.append(clipped)
    kept.sort(key=lambda item: int(item.get("line_start") or 0))
    for index, child in enumerate(kept):
        child_start = int(child["line_start"])
        if index < len(kept) - 1:
            next_start = int(kept[index + 1]["line_start"])
            child["line_end"] = max(child_start, next_start - 1)
        else:
            child["line_end"] = max(child_start, min(int(child["line_end"]), line_end))
    return kept


def merge_indexes(primary: dict, fallback: dict) -> tuple[dict, dict]:
    primary_chapters = [ch for ch in primary.get("chapters") or [] if isinstance(ch, dict)]
    fallback_chapters = [ch for ch in fallback.get("chapters") or [] if isinstance(ch, dict)]

    by_key: dict[str, dict] = {}
    order_keys: list[str] = []

    for chapter in primary_chapters:
        if not _valid_range(chapter):
            continue
        key = semantic_key_for_chapter(chapter)
        if key not in by_key:
            order_keys.append(key)
        by_key[key] = dict(chapter)

    added_top: list[str] = []
    filled_children: list[str] = []

    for chapter in fallback_chapters:
        if not _valid_range(chapter):
            continue
        key = semantic_key_for_chapter(chapter)
        if key not in by_key:
            by_key[key] = dict(chapter)
            order_keys.append(key)
            added_top.append(str(chapter.get("title") or key))
            continue

        existing = by_key[key]
        existing_children = existing.get("children") or []
        fallback_children = chapter.get("children") or []
        if (
            _parent_allows_children(existing)
            and (not isinstance(existing_children, list) or len(existing_children) == 0)
            and isinstance(fallback_children, list)
            and fallback_children
        ):
            clipped = _clip_children_to_parent(existing, fallback_children)
            if clipped:
                existing["children"] = clipped
                filled_children.append(str(existing.get("title") or key))

    # Prefer fallback children when primary has fewer note/profile/mda children.
    for chapter in fallback_chapters:
        if not _valid_range(chapter):
            continue
        key = semantic_key_for_chapter(chapter)
        existing = by_key.get(key)
        if existing is None or not _parent_allows_children(existing):
            continue
        existing_children = existing.get("children") or []
        fallback_children = chapter.get("children") or []
        if not isinstance(fallback_children, list) or not fallback_children:
            continue
        if isinstance(existing_children, list) and len(existing_children) >= 2:
            continue
        if isinstance(existing_children, list) and len(existing_children) >= len(fallback_children):
            continue
        clipped = _clip_children_to_parent(existing, fallback_children)
        if clipped and (
            not isinstance(existing_children, list) or len(clipped) > len(existing_children)
        ):
            existing["children"] = clipped
            title = str(existing.get("title") or key)
            if title not in filled_children:
                filled_children.append(title)

    merged_chapters = [by_key[key] for key in order_keys if key in by_key]
    # Also include any primary-invalid skipped? No — only valid ranges.
    max_line = 0
    for source in (primary_chapters, fallback_chapters, merged_chapters):
        for chapter in source:
            end = chapter.get("line_end")
            if isinstance(end, int):
                max_line = max(max_line, end)

    merged_chapters = fix_top_level_ranges(merged_chapters, total_lines=max_line or None)

    result = dict(primary)
    result["chapters"] = merged_chapters
    result["index_version"] = primary.get("index_version") or fallback.get("index_version") or 2
    for field in ("report_file", "company", "ticker", "year"):
        if not result.get(field) and fallback.get(field) not in (None, ""):
            result[field] = fallback[field]

    summary = {
        "primary_chapters": len(primary_chapters),
        "fallback_chapters": len(fallback_chapters),
        "merged_chapters": len(merged_chapters),
        "added_top_level": added_top,
        "filled_children": filled_children,
    }
    return result, summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fill missing top-level chapters / empty children from an MD-fallback index."
    )
    parser.add_argument("primary", type=Path, help="Primary outline-based .sections.json")
    parser.add_argument(
        "--from",
        dest="fallback",
        type=Path,
        required=True,
        help="MD-fallback .sections.json (from build_minimal_index.py)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path (default: overwrite primary)",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    if not args.primary.is_file():
        print(json.dumps({"error": f"primary not found: {args.primary}"}, ensure_ascii=False))
        return 1
    if not args.fallback.is_file():
        print(json.dumps({"error": f"fallback not found: {args.fallback}"}, ensure_ascii=False))
        return 1

    try:
        primary = _load_index(args.primary)
        fallback = _load_index(args.fallback)
        merged, summary = merge_indexes(primary, fallback)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    output_path = args.output or args.primary
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2 if args.pretty else None),
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
