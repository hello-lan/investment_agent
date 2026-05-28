#!/usr/bin/env python3
"""一键采集所有年份的财报章节数据，输出结构化 working_data.md。

用法:
    python3 scripts/collect_data.py <split_dir> <output_dir> [--code CODE]

输入: split_dir 下的年份子目录（如 2023/ 2024/ 2025/），每年含切割后的章节 .md 文件
输出:
    <output_dir>/working_data.md — 三张财务报表的结构化多年对比表 + 附注关键数据
    <output_dir>/chapters_concat.md — 非报表章节的多年全文拼接

工作流:
    1. 扫描 split_dir 发现年份目录和章节文件
    2. 三张财务报表 → 解析 markdown 表格，输出多年对比表
    3. 其他章节 → 按类型拼接多年全文
    4. 附注 → 调用 extract_notes.sh 提取关键段落
"""

import argparse
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path


# ── 章节类型与文件名匹配模式（按优先级排序，先匹配先得）──
# 子章节文件: ch10_第十节_财务报告_ch01_审计报告.md
# 顶级章节: ch06_第六节_重要事项.md
CHAPTER_PATTERNS = [
    ("审计报告", r"ch\d+_.*审计"),
    ("主要财务指标", r"ch\d+_.*主要财务"),
    ("重要事项", r"ch\d+_.*重要事项"),
    ("股东情况", r"ch\d+_.*股东"),
    ("合并资产负债表", r"合并资产负债表"),
    ("合并利润表", r"合并利润表"),
    ("合并现金流量表", r"合并现金流量表"),
    ("合并财务报表附注", r"合并财务报表附注|财务报表附注"),
]

# 三张财务报表（需要结构化解析）
FINANCIAL_STATEMENTS = {"合并资产负债表", "合并利润表", "合并现金流量表"}

# 非报表章节（全文拼接）
TEXT_CHAPTERS = ["审计报告", "主要财务指标", "重要事项", "股东情况"]


def nfkc(text: str) -> str:
    """NFKC 归一化，处理 PDF 转换引入的 CJK 兼容字符。"""
    return unicodedata.normalize("NFKC", text)


def discover_years(split_dir: Path) -> list[str]:
    """发现年份子目录，返回排序后的年份列表。"""
    years = []
    for d in sorted(split_dir.iterdir()):
        if d.is_dir() and re.match(r"^\d{4}$", d.name):
            years.append(d.name)
    return years


def discover_files(
    split_dir: Path, years: list[str],
) -> dict[str, dict[str, Path]]:
    """发现所有章节文件。返回: {chapter_type: {year: filepath}}"""
    result: dict[str, dict[str, Path]] = {}
    for ch_name, pattern in CHAPTER_PATTERNS:
        result[ch_name] = {}
        compiled = re.compile(pattern)
        for year in years:
            year_dir = split_dir / year
            if not year_dir.exists():
                continue
            for f in sorted(year_dir.glob("*.md")):
                fname = nfkc(f.stem)
                if compiled.search(fname):
                    result[ch_name][year] = f
                    break  # 取第一个匹配
    return result


# ── 财务报表解析 ──


def parse_financial_table(text: str) -> list[tuple[str, list[str]]]:
    """解析 markdown 表格，提取 (项目名称, [金额列...])。

    只处理含 "项目" 的表头行之后的内容（跳过文件开头可能残留的前一章节数据）。
    跳过: 表头行、分隔行、分类标题行（如 "流动资产："）、空行。
    """
    rows: list[tuple[str, list[str]]] = []
    header_found = False

    for line in text.split("\n"):
        line = nfkc(line.strip())
        if not line or "|" not in line:
            continue

        cells = [c.strip() for c in line.split("|")]
        # 去掉首尾空字符串（由 | 分割产生）
        cells = [c for c in cells if c or cells.index(c) not in (0, len(cells) - 1)]
        if not cells:
            continue

        first = cells[0]

        # 检测表头行（含"项目"），标记从此行之后开始收集数据
        if re.search(r"项目", first):
            header_found = True
            continue

        # 表头行之前的内容全部跳过（可能是前一章节残留数据）
        if not header_found:
            continue

        # 跳过分隔行 (| --- | --- |)
        if all(re.match(r"^-+$", c) for c in cells if c):
            continue

        # 跳过分类标题行（末尾是冒号，或只有第一列有值）
        non_empty = [c for c in cells if c]
        if len(non_empty) == 1 and (first.endswith("：") or first.endswith(":")):
            continue

        # 提取金额列（跳过"附注"列）
        # 标准格式: | 项目 | 附注 | 期末金额 | 期初金额 |
        # cells[0] = 项目名, cells[1] = 附注, cells[2:] = 金额
        if len(cells) >= 3:
            item_name = first
            # 判断 cells[1] 是否是附注列（非数字则视为附注列，跳过）
            val_cells = cells[2:] if not _is_number(cells[1]) else cells[1:]
            rows.append((item_name, val_cells))

    return rows


def _normalize_item_name(name: str) -> str:
    """标准化项目名称：去除所有空白字符（PDF 转换常在字符间插入空格）。"""
    return re.sub(r"\s+", "", nfkc(name))


def _is_number(s: str) -> bool:
    """判断字符串是否为数字（含负号、逗号分隔）。"""
    cleaned = s.replace(",", "").replace("，", "").replace("-", "").replace(" ", "")
    return bool(cleaned) and cleaned.replace(".", "").isdigit()


def build_multi_year_table(
    chapter_name: str,
    files_by_year: dict[str, Path],
) -> str:
    """解析一张财务报表的多年数据，输出 markdown 多年对比表。

    只取每行的第一个金额列（期末/本期金额），跳过期初列。
    """
    years = sorted(files_by_year.keys())
    if not years:
        return f"### {chapter_name}\n\n*（未找到文件）*\n\n"

    # 解析每年数据
    yearly_data: dict[str, list[tuple[str, list[str]]]] = {}
    for year in years:
        text = files_by_year[year].read_text(encoding="utf-8")
        yearly_data[year] = parse_financial_table(text)

    # 合并所有科目名（保持出现顺序，用归一化名去重）
    # display_names: normalized → 首次出现的原始名称（用于显示）
    all_items_norm: list[str] = []
    display_names: dict[str, str] = {}
    seen: set[str] = set()
    for year in years:
        for item_name, _ in yearly_data[year]:
            norm = _normalize_item_name(item_name)
            if norm and norm not in seen:
                all_items_norm.append(norm)
                display_names[norm] = item_name.strip()
                seen.add(norm)

    # 为每年数据建立归一化名索引，加速查找
    yearly_index: dict[str, dict[str, list[str]]] = {}
    for year in years:
        idx: dict[str, list[str]] = {}
        for row_name, row_vals in yearly_data[year]:
            norm = _normalize_item_name(row_name)
            if norm and norm not in idx:
                idx[norm] = row_vals
        yearly_index[year] = idx

    # 构建多年对比表
    lines = [f"### {chapter_name}\n"]
    header = "| 项目 | " + " | ".join(years) + " |"
    sep = "|------|" + "|".join(["------"] * len(years)) + "|"
    lines.append(header)
    lines.append(sep)

    for norm in all_items_norm:
        display = display_names[norm]
        values = []
        for year in years:
            row_vals = yearly_index[year].get(norm)
            if row_vals is not None:
                val = row_vals[0] if row_vals else ""
                values.append(val if val else "-")
            else:
                values.append("-")
        lines.append(f"| {display} | " + " | ".join(values) + " |")

    lines.append("")
    return "\n".join(lines)


# ── 非报表章节拼接 ──


def concat_text_chapters(
    files_by_year: dict[str, Path],
    chapter_name: str,
) -> str:
    """拼接非报表章节的多年全文。"""
    years = sorted(files_by_year.keys())
    if not years:
        return f"### {chapter_name}\n\n*（未找到文件）*\n\n"

    parts = [f"### {chapter_name}\n"]
    for year in years:
        text = files_by_year[year].read_text(encoding="utf-8")
        parts.append(f"\n#### {year}年\n")
        parts.append(text)
        parts.append("")
    return "\n".join(parts)


# ── 附注提取 ──


def extract_notes(notes_path: Path, output_dir: Path) -> str:
    """调用 extract_notes.sh 提取附注关键段落。"""
    script_dir = Path(__file__).parent
    extract_script = script_dir / "extract_notes.sh"
    if not extract_script.exists():
        return "*（extract_notes.sh 不存在）*"

    working_data = output_dir / "working_data.md"
    try:
        result = subprocess.run(
            ["bash", str(extract_script), str(notes_path), str(working_data)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return f"*附注关键数据已通过 extract_notes.sh 追加到 working_data.md*"
        return f"*附注提取失败: {result.stderr.strip()[:200]}*"
    except Exception as e:
        return f"*附注提取异常: {e}*"


# ── 主流程 ──


def main():
    parser = argparse.ArgumentParser(
        description="一键采集财报章节数据，输出 working_data.md + chapters_concat.md",
    )
    parser.add_argument("split_dir", help="切割文件根目录，如 data/reports/601958/3_split/")
    parser.add_argument("output_dir", help="输出目录，如 data/reports/601958/4_output/")
    parser.add_argument("--code", default="", help="股票代码（用于报告标题）")
    args = parser.parse_args()

    split_dir = Path(args.split_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not split_dir.exists():
        print(f"ERROR: split_dir 不存在: {split_dir}", file=sys.stderr)
        sys.exit(1)

    # 1. 发现年份和文件
    years = discover_years(split_dir)
    if not years:
        print(f"ERROR: 未在 {split_dir} 下发现年份目录", file=sys.stderr)
        sys.exit(1)

    file_map = discover_files(split_dir, years)
    code = args.code or split_dir.parent.name
    print(f"[collect_data] 股票代码: {code}", file=sys.stderr)
    print(f"[collect_data] 发现 {len(years)} 年数据: {', '.join(years)}", file=sys.stderr)
    for ch, ym in file_map.items():
        found = [f"{y}:{f.name}" for y, f in sorted(ym.items())]
        status = ", ".join(found) if found else "(未找到)"
        print(f"  {ch}: {status}", file=sys.stderr)

    # 2. 构建 working_data.md
    year_range = f"{years[0]}-{years[-1]}" if len(years) > 1 else years[0]
    wd_lines = [f"## {code} 财务数据提取（{year_range}）\n"]

    # 2a. 三张财务报表 → 结构化解析
    for ch_name in ["合并资产负债表", "合并利润表", "合并现金流量表"]:
        files = file_map.get(ch_name, {})
        if files:
            table_md = build_multi_year_table(ch_name, files)
            wd_lines.append(table_md)
        else:
            wd_lines.append(f"### {ch_name}\n\n*（未找到文件）*\n")

    # 2b. 附注 → 调用 extract_notes.sh（追加到 working_data.md）
    notes_files = file_map.get("合并财务报表附注", {})
    notes_status = ""
    if notes_files:
        latest_year = sorted(notes_files.keys())[-1]
        notes_path = notes_files[latest_year]
        wd_lines.append(f"### 附注关键数据（{latest_year}年）\n")
        # 先写入主体，再让 extract_notes.sh 追加
        wd_path = output_dir / "working_data.md"
        wd_path.write_text("\n".join(wd_lines), encoding="utf-8")
        notes_status = extract_notes(notes_path, output_dir)
        wd_lines.append(notes_status)
        wd_lines.append("")
    else:
        wd_lines.append("### 附注关键数据\n\n*（未找到附注文件）*\n")

    # 3. 写入 working_data.md（如果附注未写入）
    wd_path = output_dir / "working_data.md"
    if not notes_files:
        wd_path.write_text("\n".join(wd_lines), encoding="utf-8")
    print(f"[collect_data] 已写入: {wd_path} ({wd_path.stat().st_size:,} bytes)", file=sys.stderr)

    # 4. 构建 chapters_concat.md（非报表章节全文拼接）
    concat_parts = []
    for ch_name in TEXT_CHAPTERS:
        files = file_map.get(ch_name, {})
        concat_parts.append(concat_text_chapters(files, ch_name))

    concat_path = output_dir / "chapters_concat.md"
    concat_path.write_text("\n".join(concat_parts), encoding="utf-8")
    print(
        f"[collect_data] 已写入: {concat_path} ({concat_path.stat().st_size:,} bytes)",
        file=sys.stderr,
    )

    # 5. 输出摘要到 stdout（供子Agent确认）
    print(f"\n[collect_data] 采集完成")
    print(f"  working_data.md: {wd_path.stat().st_size:,} bytes")
    print(f"  chapters_concat.md: {concat_path.stat().st_size:,} bytes")
    print(f"  文件发现摘要:")
    for ch, ym in file_map.items():
        print(f"    {ch}: {len(ym)}/{len(years)} 年")


if __name__ == "__main__":
    main()
