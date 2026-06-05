#!/usr/bin/env python3
"""一键采集所有年份的财报章节数据，输出 data_manifest.md（文件清单 + 结构化报表）。

用法:
    python3 scripts/collect_data.py <split_dir> <output_dir> [--code CODE]

输入: split_dir 下的年份子目录（如 2023/ 2024/ 2025/），每年含切割后的章节 .md 文件
输出:
    <output_dir>/data_manifest.md — 文件清单（大小、推荐读取方式）+ 三张财务报表多年对比表

设计原则（参考 split-financial-report 的 LLM 协同模式）：
    - 脚本完成机械工作：文件发现、大小估算、结构化表格解析
    - 非结构化数据（附注、审计报告、股东情况等）输出文件清单供 LLM 一次性全读
    - 不对非结构化数据做正则提取（会过拟合不同公司/年份的格式差异）
"""

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path


# ── 章节类型与文件名匹配模式（按优先级排序，先匹配先得）──
CHAPTER_PATTERNS = [
    # 财务报表（结构化解析）
    ("合并资产负债表", r"合并资产负债表"),
    ("合并利润表", r"合并利润表"),
    ("合并现金流量表", r"合并现金流量表"),
    # 文本章节（LLM 一次性全读）
    ("审计报告", r"ch\d+_.*审计(?!报告及)"),
    ("主要财务指标", r"ch\d+_.*主要财务"),
    ("重要事项", r"ch\d+_.*重要事项"),
    ("股东情况", r"ch\d+_.*股东"),
    ("合并财务报表附注", r"合并财务报表附注|财务报表附注"),
]

# 三张财务报表（需要结构化解析，由脚本完成）
FINANCIAL_STATEMENTS = {"合并资产负债表", "合并利润表", "合并现金流量表"}

# LLM 需要一次性全读的文本章节
TEXT_CHAPTERS = ["审计报告", "主要财务指标", "重要事项", "股东情况", "合并财务报表附注"]

# 文件大小阈值
SMALL_FILE_THRESHOLD = 50_000   # < 50KB → 全文 cat
LARGE_FILE_THRESHOLD = 100_000  # > 100KB → 分段策略读取

# 各章节包含的关键数据（用于清单中的"包含数据"列）
CHAPTER_DATA_DESC = {
    "主要财务指标": "EPS、ROE、扣非净利润、非经常性损益明细、季度营收分解",
    "审计报告": "审计意见类型、审计机构名称、签字会计师、关键审计事项",
    "重要事项": "关联交易金额/占比、重大担保、诉讼、处罚/整改、会计政策变更",
    "股东情况": "大股东持股比例、质押数量/比例趋势、司法冻结/标记记录",
    "合并财务报表附注": "⚠️ 大文件: 应收账龄结构、存货构成明细、受限资金分类、商誉减值测试、有息负债明细、会计估计变更",
    "合并资产负债表": "（已由脚本解析为结构化表格，不需再读原始文件）",
    "合并利润表": "（已由脚本解析为结构化表格，不需再读原始文件）",
    "合并现金流量表": "（已由脚本解析为结构化表格，不需再读原始文件）",
}


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


# 母公司报表关键词（文件名含这些词 → 跳过，只用合并报表）
_PARENT_KEYWORDS = [
    "母公司资产负债表", "母公司利润表", "母公司现金流量表",
    "母公司所有者权益变动表", "母公司股东权益变动表",
    "公司资产负债表", "公司利润表", "公司现金流量表",
    "公司所有者权益变动表", "公司股东权益变动表",
]


def _is_parent_statement(fname: str) -> bool:
    """判断文件名是否为母公司报表（应跳过）。"""
    fname_nfkc = nfkc(fname)
    for kw in _PARENT_KEYWORDS:
        if kw in fname_nfkc:
            return True
    return False


def _has_consolidated_marker(fname: str) -> bool:
    """判断文件名是否明确标记为合并报表。"""
    return "合并" in nfkc(fname)


def discover_files(
    split_dir: Path, years: list[str],
) -> dict[str, dict[str, Path]]:
    """发现所有章节文件。返回: {chapter_type: {year: filepath}}。

    优先选择"合并"版本的文件（跳过母公司报表）。
    同时搜索年份目录下的直接文件 + 子目录（如 财务报告_子章节/）中的文件。
    """
    result: dict[str, dict[str, Path]] = {}
    for ch_name, pattern in CHAPTER_PATTERNS:
        result[ch_name] = {}
        compiled = re.compile(pattern)
        for year in years:
            year_dir = split_dir / year
            if not year_dir.exists():
                continue

            # 收集候选文件：目录下直接 .md + 一级子目录下的 .md
            candidates: list[Path] = sorted(year_dir.glob("*.md"))
            for subdir in sorted(year_dir.iterdir()):
                if subdir.is_dir():
                    candidates.extend(sorted(subdir.glob("*.md")))

            # 过滤：匹配模式 + 非母公司 + 优先合并版本
            merged_match: Path | None = None
            fallback_match: Path | None = None
            for f in candidates:
                fname = nfkc(f.stem)
                if not compiled.search(fname):
                    continue
                if _is_parent_statement(fname):
                    continue  # 明确跳过母公司报表
                if _has_consolidated_marker(fname):
                    merged_match = f
                    break  # 找到合并版本，立即采纳
                if fallback_match is None:
                    fallback_match = f  # 无"合并"标记但匹配了模式，作为备选

            best = merged_match or fallback_match
            if best:
                result[ch_name][year] = best
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


# ── 文件清单构建 ──


def _fmt_size(size_bytes: int) -> str:
    """格式化文件大小为人可读形式。"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


def _read_recommendation(chapter_name: str, size_bytes: int) -> str:
    """根据章节类型和文件大小推荐读取方式。"""
    if chapter_name in FINANCIAL_STATEMENTS:
        return "✅ 已由脚本解析为结构化表格，不需读原始文件"
    if size_bytes < SMALL_FILE_THRESHOLD:
        return f"`cat` 全文读取（< 50KB）"
    if size_bytes > LARGE_FILE_THRESHOLD:
        return f"⚠️ 大文件，分段策略：先 `grep -n` 定位关键段落行号，再 `sed -n` 一次性读取所有段落"
    return f"`cat` 全文读取"


def build_file_inventory(
    file_map: dict[str, dict[str, Path]],
    years: list[str],
) -> str:
    """构建文件清单：包含大小、数据类型、推荐读取方式。"""
    lines = [
        "## 文件清单\n",
        "| 文件 | 年份 | 大小 | 包含数据 | 读取方式 |",
        "|------|------|------|----------|----------|",
    ]

    # 按章节分组输出
    for ch_name in [
        "主要财务指标", "审计报告", "重要事项", "股东情况",
        "合并资产负债表", "合并利润表", "合并现金流量表",
        "合并财务报表附注",
    ]:
        files = file_map.get(ch_name, {})
        for year in sorted(files.keys()):
            fpath = files[year]
            size = fpath.stat().st_size if fpath.exists() else 0
            desc = CHAPTER_DATA_DESC.get(ch_name, "")
            rec = _read_recommendation(ch_name, size)
            lines.append(
                f"| {ch_name} | {year} | {_fmt_size(size)} | {desc} | {rec} |"
            )

    lines.append("")
    return "\n".join(lines)


# ── 非结构化章节信息输出 ──


def build_text_chapter_summary(
    file_map: dict[str, dict[str, Path]],
    years: list[str],
) -> str:
    """为非结构化章节输出简要信息，引导 LLM 按需读取。"""
    parts = ["## 文本章节位置索引\n"]
    parts.append("以下文件需 LLM 按需一次性全文读取（每文件只读一次）：\n")

    for ch_name in TEXT_CHAPTERS:
        if ch_name in FINANCIAL_STATEMENTS:
            continue
        files = file_map.get(ch_name, {})
        if not files:
            parts.append(f"- **{ch_name}**: ⚠️ 未找到文件\n")
            continue

        parts.append(f"### {ch_name}\n")
        for year in sorted(files.keys()):
            fpath = files[year]
            size = fpath.stat().st_size
            parts.append(f"- **{year}年**: `{fpath}` ({_fmt_size(size)})\n")
        parts.append("")

    return "\n".join(parts)


# ── 读取策略指南 ──


def build_reading_guide() -> str:
    """输出 LLM 数据加载指南。"""
    return """## LLM 数据加载指南

### 核心规则（必须严格遵守）

1. **每个文件只读一次** — 读取前规划好该文件需要提取的所有数据点，一次读完全部提取
2. **读取前先估算大小** — 用 `wc -c <file>` 确认文件大小，避免超大文件撑爆上下文
3. **禁止反复读取** — 读完一个文件后禁止回头再读同一文件提取其他指标
4. **读完后纯推理** — 所有数据加载完成后，分析阶段禁止调用工具读文件，仅允许写入报告

### 大文件（>100KB）分段读取策略

附注文件通常 300-500KB，采用两步法：

**第1步**：一次性定位所有目标段落行号（1次 grep，覆盖全部目标）：
```bash
grep -n "^[0-9]*、 货币资金$\\|^[0-9]*、 应收票据$\\|^[0-9]*、 应收账款$\\|^[0-9]*、 预付款项$\\|^[0-9]*、 存货$\\|^[0-9]*、 固定资产$\\|^[0-9]*、 在建工程$\\|^[0-9]*、 商誉$\\|^[0-9]*、 短期借款$\\|^[0-9]*、 长期借款$\\|关联交易情况\\|所有权或使用权受到限制" <附注文件>
```

**第2步**：根据定位结果，一次性读取所有关键段落（1次 sed，多个行号范围）：
```bash
sed -n '<行号1>,<行号1+80>p;<行号2>,<行号2+80>p;...' <附注文件>
```

如果 grep 未匹配到标准标题（格式异常），改用 `head -200` 查看附注前 200 行确认结构后重新定位。

### 读取顺序建议

| 优先级 | 文件 | 读取方式 | 一次提取目标 |
|--------|------|----------|------------|
| 1 | data_manifest.md | cat | 加载结构化报表 + 文件清单 |
| 2 | ch02_主要财务指标 (所有年份) | cat 全文 | EPS、ROE、扣非利润、非经常损益明细、季度营收、审计信息（如含在ch02中） |
| 3 | 审计报告 (所有年份) | cat 全文 | 审计意见、审计机构、签字会计师、关键审计事项 |
| 4 | 股东情况 (所有年份) | cat 全文 | 大股东持股/质押比例趋势、司法冻结、违规担保 |
| 5 | 重要事项 (所有年份) | cat 全文 | 关联交易金额/占比、重大担保/诉讼、处罚、会计政策变更 |
| 6 | 合并财务报表附注 (最新年份) | 分段策略 | 应收账龄、存货构成、受限资金、商誉减值、有息负债 |

完成上述读取后即可开始纯推理分析，禁止再读任何文件。
"""



# ── 匹配校验清单 ──


def build_verification_checklist(
    file_map: dict[str, dict[str, Path]],
    split_dir: Path,
    years: list[str],
) -> str:
    """生成 LLM 校验清单：脚本匹配结果 + 未匹配的文件列表。

    参考 split-financial-report 的输出格式（✓/⚠️/❌ 标记），
    让 LLM 快速发现匹配错误并手动纠正。
    """
    parts = ["## 文件匹配校验清单\n"]
    parts.append(
        "> ⚠️ **脚本的正则匹配可能因格式差异而出错**。"
        "请在加载数据前快速校验以下匹配结果，"
        "确认文件类别正确后再开始读取。\n"
    )

    # 已匹配的章节类型
    matched_paths: set[str] = set()
    parts.append("### 已匹配文件\n")
    parts.append("| 校验 | 章节类型 | 年份 | 匹配文件 | 大小 |")
    parts.append("|------|---------|------|---------|------|")
    for ch_name in [
        "主要财务指标", "审计报告", "重要事项", "股东情况",
        "合并资产负债表", "合并利润表", "合并现金流量表",
        "合并财务报表附注",
    ]:
        files = file_map.get(ch_name, {})
        for year in sorted(files.keys()):
            fpath = files[year]
            size = fpath.stat().st_size
            matched_paths.add(str(fpath))
            # 标记匹配可靠性：财务报表检查"合并"标记，文本章节检查文件名含章节关键词
            if ch_name in FINANCIAL_STATEMENTS or "合并" in nfkc(fpath.stem):
                flag = "✅"
            elif nfkc(ch_name) in nfkc(fpath.stem):
                flag = "✅"
            else:
                flag = "⚠️ fallback"
            parts.append(
                f"| {flag} | {ch_name} | {year} | "
                f"`{fpath.relative_to(split_dir.parent)}` | {_fmt_size(size)} |"
            )

    # 缺失的章节
    missing = []
    for ch_name in [
        "主要财务指标", "审计报告", "重要事项", "股东情况",
        "合并资产负债表", "合并利润表", "合并现金流量表",
        "合并财务报表附注",
    ]:
        files = file_map.get(ch_name, {})
        for year in years:
            if year not in files:
                missing.append((ch_name, year))
    if missing:
        parts.append("\n### ❌ 未找到\n")
        for ch_name, year in missing:
            parts.append(f"- **{ch_name}** / {year}年: 未匹配到文件")

    parts.append("")

    # 未匹配的文件（脚本不认识的文件，可能包含遗漏数据）
    all_files: list[tuple[str, Path, int]] = []
    for year in years:
        year_dir = split_dir / year
        if not year_dir.exists():
            continue
        for f in sorted(year_dir.glob("*.md")):
            all_files.append((year, f, f.stat().st_size))
        for subdir in sorted(year_dir.iterdir()):
            if subdir.is_dir():
                for f in sorted(subdir.glob("*.md")):
                    all_files.append((year, f, f.stat().st_size))

    unmatched = [
        (y, f, s) for y, f, s in all_files
        if str(f) not in matched_paths
        and not _is_parent_statement(f.stem)
    ]
    if unmatched:
        parts.append("### 🔍 未匹配文件（脚本未识别，按大小排序）\n")
        parts.append("> LLM 需检查这些文件中是否包含遗漏的关键数据。\n")
        parts.append("| 年份 | 文件 | 大小 |")
        parts.append("|------|------|------|")
        for year, fpath, size in sorted(unmatched, key=lambda x: -x[2]):
            parts.append(
                f"| {year} | `{fpath.relative_to(split_dir.parent)}` | {_fmt_size(size)} |"
            )
        parts.append("")

    return "\n".join(parts)


# ── Fallback 提示 ──


def build_fallback_hints(
    file_map: dict[str, dict[str, Path]],
    split_dir: Path,
    years: list[str],
) -> str:
    """当附注未找到时，提供智能 fallback 建议。

    附注可能在：
    1. 财务报告原始文件（未二次切割，整章在一个文件里）
    2. 其他以"合并"开头的大文件（如合并所有者权益变动表）
    3. 财务报告_子章节 目录下的其他文件
    """
    notes_files = file_map.get("合并财务报表附注", {})
    found_years = set(notes_files.keys())
    missing_years = [y for y in years if y not in found_years]

    if not missing_years:
        # 所有年份都有附注
        parts = ["### 数据完整性\n"]
        parts.append("✅ 所有年份均已找到合并财务报表附注。\n\n")
        # 仍有提示：提醒 LLM 校验文件内容
        parts.append(
            "> 建议校验：`head -5` 查看附注文件前5行，确认内容确实是财务报表附注"
            "（而非审计报告或其他章节），如有疑问再 `grep -n '货币资金\\|应收账款\\|存货'` 快速确认。\n"
        )
        return "\n".join(parts)

    parts = ["### ⚠️ 附注缺失 Fallback\n"]
    parts.append(
        f"> 以下年份未找到独立的 **合并财务报表附注** 文件: {', '.join(missing_years)}。\n"
    )
    parts.append(
        "> 附注内容通常出现在以下位置之一，请 LLM 按优先级排查：\n"
    )

    for year in missing_years:
        parts.append(f"\n#### {year}年 附注 fallback 候选:\n")
        year_dir = split_dir / year
        if not year_dir.exists():
            parts.append(f"*年份目录不存在: {year_dir}*\n")
            continue

        # 收集候选文件（排除已匹配的 + 母公司报表）
        candidates: list[tuple[str, Path, int]] = []
        for f in sorted(year_dir.glob("*.md")):
            fname = nfkc(f.stem)
            if not _is_parent_statement(fname):
                candidates.append(("", f, f.stat().st_size))
        for subdir in sorted(year_dir.iterdir()):
            if subdir.is_dir():
                for f in sorted(subdir.glob("*.md")):
                    fname = nfkc(f.stem)
                    if not _is_parent_statement(fname):
                        candidates.append((subdir.name + "/", f, f.stat().st_size))

        if not candidates:
            parts.append("*无候选文件*\n")
            continue

        # 找最大文件（附注通常是最大文件之一）
        candidates.sort(key=lambda x: -x[2])
        largest = candidates[0]
        parts.append(
            f"1. **最可能**: `{largest[0]}{largest[1].name}` "
            f"({_fmt_size(largest[2])}) — 目录中最大的 md 文件\n"
        )
        parts.append(
            f"   ```bash\n"
            f"   grep -n '财务报表附注\\|项目注释\\|应收账款\\|存货\\|货币资金' "
            f"'{largest[1]}' | head -10\n"
            f"   ```\n"
        )

        # 列出所有候选（按大小降序，top 5）
        parts.append("2. **候选清单**（按文件大小降序，前5个）:\n")
        parts.append("   | 文件 | 大小 |")
        parts.append("   |------|------|")
        for prefix, f, size in candidates[:5]:
            fname = f"{prefix}{f.name}"
            parts.append(f"   | `{fname}` | {_fmt_size(size)} |")

        # 给出确认命令
        parts.append(
            f"\n3. **确认命令**: 对上述候选依次运行 `grep -l '合并财务报表项目注释\\|财务报表附注'`"
            "确定哪个文件真正包含附注内容。找到后按大文件分段策略读取。\n"
        )

    parts.append("")
    return "\n".join(parts)


# ── 主流程 ──


def main():
    parser = argparse.ArgumentParser(
        description="一键生成财报数据清单 data_manifest.md（文件清单 + 结构化报表）",
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

    # 扫描是否有被跳过的母公司报表（stderr 警告）
    parent_found = []
    for year in years:
        year_dir = split_dir / year
        if not year_dir.exists():
            continue
        candidates = sorted(year_dir.glob("*.md"))
        for subdir in sorted(year_dir.iterdir()):
            if subdir.is_dir():
                candidates.extend(sorted(subdir.glob("*.md")))
        for f in candidates:
            if _is_parent_statement(f.stem):
                parent_found.append(f"{year}/{f.name}")
    if parent_found:
        print(
            f"[collect_data] ⚠️ 发现并跳过母公司报表 {len(parent_found)} 个:",
            file=sys.stderr,
        )
        for pf in parent_found[:5]:
            print(f"  - {pf}", file=sys.stderr)
        if len(parent_found) > 5:
            print(f"  ... 等共 {len(parent_found)} 个", file=sys.stderr)

    code = args.code or split_dir.parent.name
    year_range = f"{years[0]}-{years[-1]}" if len(years) > 1 else years[0]

    # stderr: 文件发现摘要
    print(f"[collect_data] 股票代码: {code}", file=sys.stderr)
    print(f"[collect_data] 发现 {len(years)} 年数据: {', '.join(years)}", file=sys.stderr)
    for ch, ym in file_map.items():
        found = [f"{y}:{f.name}" for y, f in sorted(ym.items())]
        status = ", ".join(found) if found else "(未找到)"
        print(f"  {ch}: {status}", file=sys.stderr)

    # 2. 构建 data_manifest.md
    lines = [
        f"# {code} 财报数据清单（{year_range}）\n",
        f"> 生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 股票代码: {code}",
        f"> 覆盖年份: {', '.join(years)}",
        f"> 数据来源: {split_dir}",
        f"> ⚠️ **口径声明**: 以下所有财务报表和附注均为**合并报表口径**（非母公司报表）。母公司报表已被自动排除。分析时禁止引用母公司数据。",
        "",
    ]

    # 2a. 文件匹配校验清单（新增：LLM 校验脚本匹配结果）
    lines.append(build_verification_checklist(file_map, split_dir, years))
    lines.append("---\n")

    # 2b. 文件清单
    lines.append(build_file_inventory(file_map, years))
    lines.append("---\n")

    # 2c. LLM 读取策略指南
    lines.append(build_reading_guide())
    lines.append("---\n")

    # 2c. 三张财务报表 → 结构化解析（保留）
    lines.append(f"## 结构化财务报表（{year_range}）\n")
    lines.append("> 以下数据已由脚本从原始 markdown 表格中解析，LLM 不需再读原始报表文件。\n")

    for ch_name in ["合并资产负债表", "合并利润表", "合并现金流量表"]:
        files = file_map.get(ch_name, {})
        if files:
            table_md = build_multi_year_table(ch_name, files)
            lines.append(table_md)
        else:
            lines.append(f"### {ch_name}\n\n*（未找到文件）*\n")

    # 2e. 文本章节快速索引
    lines.append("---\n")
    lines.append(build_text_chapter_summary(file_map, years))

    # 2f. Fallback 提示（附注缺失时的智能指引）
    lines.append("---\n")
    lines.append(build_fallback_hints(file_map, split_dir, years))

    # 3. 写入 data_manifest.md
    manifest_path = output_dir / "data_manifest.md"
    manifest_path.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"[collect_data] 已写入: {manifest_path} ({manifest_path.stat().st_size:,} bytes)",
        file=sys.stderr,
    )

    # 4. 输出摘要到 stdout（供子Agent确认）
    print(f"\n[collect_data] 采集完成")
    print(f"  data_manifest.md: {manifest_path.stat().st_size:,} bytes")
    print(f"  包含: 校验清单 + 文件清单 + 结构化财务报表 + LLM读取指南 + 文本索引 + Fallback提示")
    print(f"  文件发现摘要:")
    for ch, ym in file_map.items():
        print(f"    {ch}: {len(ym)}/{len(years)} 年")


if __name__ == "__main__":
    main()
