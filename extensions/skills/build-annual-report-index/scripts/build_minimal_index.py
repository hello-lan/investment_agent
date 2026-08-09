#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


TOP_LEVEL_RULES = [
    {
        "keywords": ["管理层讨论与分析"],
        "priority": "P0",
        "reason": "经营情况、资产负债变化与管理层叙事的核心入口",
    },
    {
        "keywords": ["财务指标", "主要财务指标", "公司简介"],
        "priority": "P1",
        "reason": "用于快速建立公司基础信息和核心财务指标的整体认知",
    },
    {
        "keywords": ["重要事项", "重大事项"],
        "priority": "P0",
        "reason": "用于快速排查重大风险、诉讼、担保和异常事项",
    },
    {
        "keywords": ["股份变动及股东情况", "股东情况"],
        "priority": "P1",
        "reason": "用于观察股东结构、筹码变化与控制权稳定性",
    },
    {
        "keywords": ["债券相关情况"],
        "priority": "P1",
        "reason": "用于确认债券融资、偿债安排与潜在信用压力",
    },
    {
        "keywords": ["优先股相关情况"],
        "priority": "P2",
        "reason": "用于确认是否存在优先股相关披露及其影响",
    },
    {
        "keywords": ["环境和社会责任"],
        "priority": "P2",
        "reason": "用于后续按需回查 ESG、环保与社会责任披露",
    },
    {
        "keywords": ["公司治理"],
        "priority": "P2",
        "reason": "用于后续按需回查治理结构、制度建设与合规披露",
    },
    {
        "keywords": ["重要提示", "目录", "释义"],
        "priority": "P2",
        "reason": "用于定位免责声明、目录结构与术语说明",
    },
]

CHAPTER_CHILD_RULES = [
    {
        "keywords": ["主营业务分析"],
        "priority": "P0",
        "reason": "管理层讨论与分析中的核心经营段落",
    },
    {
        "keywords": ["资产及负债状况分析", "资产负债状况分析"],
        "priority": "P0",
        "reason": "用于排查应收、存货、在建工程、借款与现金结构变化",
    },
    {
        "keywords": ["投资状况分析"],
        "priority": "P0",
        "reason": "用于识别资本开支、并购和金融投资相关风险",
    },
    {
        "keywords": ["未来发展的展望", "未来发展展望"],
        "priority": "P1",
        "reason": "用于理解管理层对下一阶段经营与风险的表述",
    },
]

FINANCIAL_REPORT_SPECS = [
    {
        "chapter_id": "financial_report_audit_report",
        "aliases": ["审计报告"],
        "priority": "P0",
        "reason": "用于确认审计报告类型、覆盖范围和签字信息",
    },
    {
        "chapter_id": "financial_report_consolidated_balance_sheet",
        "aliases": ["合并资产负债表"],
        "priority": "P0",
        "reason": "三张主表之一，用于查看资产、负债与资本结构",
    },
    {
        "chapter_id": "financial_report_consolidated_cash_flow_statement",
        "aliases": ["合并现金流量表"],
        "priority": "P0",
        "reason": "三张主表之一，用于查看收现质量和资金流向",
    },
    {
        "chapter_id": "financial_report_consolidated_income_statement",
        "aliases": ["合并利润表"],
        "priority": "P0",
        "reason": "三张主表之一，用于查看收入、利润与成本变化",
    },
    {
        "chapter_id": "financial_report_accounting_policy",
        "aliases": ["重要会计政策及会计估计", "重要会计政策和会计估计"],
        "priority": "P0",
        "reason": "用于确认关键会计政策、估计口径和潜在口径变动",
    },
    {
        "chapter_id": "financial_report_notes",
        "aliases": ["合并财务报表项目注释", "合并财务报表附注", "合并财务报表附注中的项目注释", "合并报表附注"],
        "priority": "P0",
        "reason": "用于按附注项目回查主表异常的解释层",
    },
]

PUNCT_TRANSLATION = str.maketrans("", "", " \t\r\n　-—_()（）[]【】{}《》<>:：;；,.，。!?！？'\"“”‘’|/\\·•")
TOP_LEVEL_TOC_PATTERN = re.compile(r"^(第[一二三四五六七八九十]+节)\s*(.+?)\s*(?:[.．·… ]+\d+)?$")
FLEX_HEADING_PATTERN = re.compile(r"^(第[一二三四五六七八九十]+节|[一二三四五六七八九十百]+、|\d+、)")
PAGE_HEADER_PATTERN = re.compile(r"^##\s*Page\s+\d+", re.IGNORECASE)
NOTE_ITEM_PATTERN = re.compile(r"^(\d+)、\s*(.+)$")
CN_CHILD_HEADING_PATTERN = re.compile(r"^([一二三四五六七八九十百]+、)\s*(.+)$")

CHINESE_NUMERAL_MAP = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass
class ChapterNode:
    chapter_id: str
    title: str
    line_start: int
    line_end: int
    priority: str
    reason: str
    children: list["ChapterNode"] = field(default_factory=list)

    def to_json(self) -> dict:
        payload = {
            "chapter_id": self.chapter_id,
            "title": self.title,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "priority": self.priority,
            "reason": self.reason,
        }
        if self.children:
            payload["children"] = [child.to_json() for child in self.children]
        return payload


@dataclass
class LocatedNode:
    chapter_id: str
    priority: str
    reason: str
    line_start: int
    title: str
    matched_alias: str
    located_in_pass: str
    line_end: int = 0
    children: list[ChapterNode] = field(default_factory=list)

    def to_chapter(self) -> ChapterNode:
        return ChapterNode(
            chapter_id=self.chapter_id,
            title=self.title,
            line_start=self.line_start,
            line_end=self.line_end,
            priority=self.priority,
            reason=self.reason,
            children=self.children,
        )


@dataclass
class TopLevelSpec:
    chapter_id: str
    aliases: list[str]
    priority: str
    reason: str
    toc_title: str
    toc_name: str
    toc_prefix: str
    order: int


def normalize(text: str) -> str:
    return text.translate(PUNCT_TRANSLATION)


def non_empty_lines(lines: list[str], start: int, stop: int) -> Iterable[tuple[int, str]]:
    for index in range(max(0, start), min(len(lines), stop)):
        line = lines[index].strip()
        if line:
            yield index + 1, line


def chinese_numeral_to_int(text: str) -> int | None:
    if not text:
        return None
    if text == "十":
        return 10
    if text.startswith("十"):
        tail = text[1:]
        return 10 + CHINESE_NUMERAL_MAP.get(tail, 0)
    if text.endswith("十"):
        head = CHINESE_NUMERAL_MAP.get(text[0])
        if head is None:
            return None
        return head * 10
    if "十" in text:
        head, tail = text.split("十", 1)
        head_value = CHINESE_NUMERAL_MAP.get(head, 1)
        tail_value = CHINESE_NUMERAL_MAP.get(tail, 0)
        return head_value * 10 + tail_value
    return CHINESE_NUMERAL_MAP.get(text)


def chapter_order_from_prefix(prefix: str) -> int:
    match = re.match(r"^第([一二三四五六七八九十]+)节$", prefix)
    if not match:
        return 0
    return chinese_numeral_to_int(match.group(1)) or 0


def detect_toc(lines: list[str], chunk_size: int = 200, max_chunks: int = 10) -> tuple[int, int, list[dict]]:
    toc_start = 0
    toc_end = 0
    entries: list[dict] = []
    seen_titles: set[str] = set()

    upper = min(len(lines), chunk_size * max_chunks)
    for chunk_end in range(chunk_size, upper + chunk_size, chunk_size):
        chunk_end = min(chunk_end, len(lines))
        chunk_lines = lines[:chunk_end]

        if not toc_start:
            for idx, raw in enumerate(chunk_lines, start=1):
                if raw.strip() == "目录":
                    toc_start = idx
                    break

        if not toc_start:
            continue

        for idx, raw in enumerate(chunk_lines[toc_start - 1 :], start=toc_start):
            stripped = raw.strip()
            if not stripped:
                continue
            match = TOP_LEVEL_TOC_PATTERN.match(stripped)
            if not match:
                continue
            full_title = f"{match.group(1)}{match.group(2)}"
            normalized_title = normalize(full_title)
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            entries.append(
                {
                    "line": idx,
                    "prefix": match.group(1),
                    "name": match.group(2).strip(),
                    "title": full_title,
                    "order": chapter_order_from_prefix(match.group(1)),
                }
            )
            toc_end = idx

        if entries and any("财务报告" in entry["title"] or "财务会计报告" in entry["title"] for entry in entries):
            break

        if len(entries) >= 6 and toc_end and chunk_end - toc_end >= 20:
            break

    return toc_start, toc_end, entries


def line_looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if PAGE_HEADER_PATTERN.match(stripped):
        return False
    if stripped.isdigit():
        return False
    if "|" in stripped:
        return False
    if len(stripped) > 80:
        return False
    if "......" in stripped or "……" in stripped:
        return False
    if stripped.startswith(("合并财务报表项目注释", "合并财务报表附注", "合并报表附注")):
        return True
    return bool(FLEX_HEADING_PATTERN.match(stripped)) or stripped.startswith(("审计报告正文", "合并资产负债表", "合并利润表", "合并现金流量表"))


def build_windows(lines: list[str], start_index: int, span: int = 3) -> list[tuple[int, str]]:
    windows = []
    for offset in range(span):
        real_index = start_index + offset
        if real_index >= len(lines):
            break
        joined = "".join(lines[real_index : min(len(lines), real_index + span)])
        windows.append((real_index + 1, normalize(joined)))
    return windows


def find_candidates(lines: list[str], aliases: list[str], search_start: int = 1, search_end: int | None = None) -> list[int]:
    search_end = search_end or len(lines)
    alias_norms = [normalize(alias) for alias in aliases]
    candidates: list[int] = []
    last_added = -99

    for index in range(max(0, search_start - 1), min(len(lines), search_end)):
        for candidate_line, normalized_window in build_windows(lines, index):
            if any(alias in normalized_window for alias in alias_norms):
                if candidate_line - last_added > 2:
                    candidates.append(candidate_line)
                    last_added = candidate_line
                break

    return candidates


def strip_heading_prefix(text: str) -> str:
    stripped = text.strip()
    stripped = re.sub(r"^第[一二三四五六七八九十]+节\s*", "", stripped)
    stripped = re.sub(r"^[一二三四五六七八九十百]+、\s*", "", stripped)
    stripped = re.sub(r"^\d+、\s*", "", stripped)
    return stripped.strip()


def line_looks_like_peer_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if PAGE_HEADER_PATTERN.match(stripped):
        return False
    if stripped.isdigit() or "|" in stripped:
        return False
    if len(stripped) > 80:
        return False
    if stripped.startswith(("母公司财务报表主要项目注释", "母公司财务报表附注", "母公司报表附注")):
        return True
    return bool(re.match(r"^(第[一二三四五六七八九十]+节|[一二三四五六七八九十百]+、)", stripped))


def clean_note_item_name(text: str) -> str:
    cleaned = re.sub(r"\s+[√□▢■].*$", "", text.strip())
    cleaned = re.sub(r"\s+(适用|不适用).*$", "", cleaned)
    return cleaned.strip()


def parse_note_item_heading(line: str) -> tuple[str, str, str] | None:
    stripped = line.strip()
    if not stripped:
        return None
    if PAGE_HEADER_PATTERN.match(stripped):
        return None
    if "|" in stripped or len(stripped) > 80:
        return None
    match = NOTE_ITEM_PATTERN.match(stripped)
    if not match:
        return None
    item_no = match.group(1)
    normalized_title = clean_note_item_name(match.group(2))
    if not normalized_title:
        return None
    if len(normalized_title) > 30:
        return None
    if any(token in normalized_title for token in ("。", "；", "：", "因此", "由于")):
        return None
    display_title = f"{item_no}、{normalized_title}"
    return item_no, normalized_title, display_title


def score_candidate(lines: list[str], candidate_line: int, aliases: list[str], toc_start: int, toc_end: int) -> tuple[int, str]:
    if toc_start and toc_start <= candidate_line <= toc_end + 2:
        return -100, "inside_toc"

    alias_norms = [normalize(alias) for alias in aliases]
    start = max(0, candidate_line - 3)
    end = min(len(lines), candidate_line + 2)
    joined = normalize("".join(lines[start:end]))
    line = lines[candidate_line - 1].strip()
    line_core = normalize(strip_heading_prefix(line))
    window = lines[max(0, candidate_line - 21) : min(len(lines), candidate_line + 20)]
    score = 0

    if any(alias in normalize(line) for alias in alias_norms):
        score += 6
    if any(alias in joined for alias in alias_norms):
        score += 5
    if line_looks_like_heading(line):
        score += 5
    elif candidate_line < len(lines) and line_looks_like_heading(lines[candidate_line].strip()):
        score += 3

    if any(line_core == alias for alias in alias_norms):
        score += 12
    elif any(line_core.startswith(alias) for alias in alias_norms):
        score += 6
    elif any(alias in line_core for alias in alias_norms):
        score += 2

    stripped_window = [item.strip() for item in window if item.strip()]
    if any("目录" == item for item in stripped_window[:3]):
        score -= 8
    if any("......" in item or "……" in item for item in stripped_window[:5]):
        score -= 8
    if any(item.startswith("浙江") and "年度报告全文" in item for item in stripped_window[:4]):
        score -= 1
    if any(token in line for token in ("详见", "附注（", "项目注释（")):
        score -= 6
    if line.isdigit() or "|" in line:
        score -= 4

    return score, "ok" if score >= 7 else "weak"


def canonical_title_from_window(lines: list[str], candidate_line: int, aliases: list[str]) -> tuple[int, str, str]:
    alias_norms = [(alias, normalize(alias)) for alias in aliases]
    for offset in range(3):
        start = candidate_line - 1 + offset
        if start >= len(lines):
            break
        segment = "".join(lines[start : min(len(lines), start + 3)])
        normalized_segment = normalize(segment)
        for alias, alias_norm in alias_norms:
            if alias_norm in normalized_segment:
                for look_ahead in range(3):
                    line_index = start + look_ahead
                    if line_index >= len(lines):
                        break
                    candidate_title = lines[line_index].strip()
                    if candidate_title and alias_norm in normalize(candidate_title):
                        return line_index + 1, candidate_title, alias
                first_non_empty_index = next((i for i in range(start, min(len(lines), start + 3)) if lines[i].strip()), start)
                return first_non_empty_index + 1, lines[first_non_empty_index].strip(), alias
    fallback_title = lines[candidate_line - 1].strip() or aliases[0]
    return candidate_line, fallback_title, aliases[0]


def locate_node(
    lines: list[str],
    chapter_id: str,
    aliases: list[str],
    priority: str,
    reason: str,
    toc_start: int,
    toc_end: int,
    search_start: int = 1,
    search_end: int | None = None,
    pass_name: str = "first_pass",
) -> LocatedNode | None:
    candidates = find_candidates(lines, aliases, search_start=search_start, search_end=search_end)
    best_match: tuple[int, int, str, str] | None = None
    seen_lines: set[int] = set()

    for candidate_line in candidates:
        resolved_line, title, matched_alias = canonical_title_from_window(lines, candidate_line, aliases)
        if resolved_line in seen_lines:
            continue
        seen_lines.add(resolved_line)
        score, _ = score_candidate(lines, resolved_line, aliases, toc_start, toc_end)
        if best_match is None or score > best_match[0] or (score == best_match[0] and resolved_line < best_match[1]):
            best_match = (score, resolved_line, title, matched_alias)

    if best_match is None or best_match[0] < 7:
        return None

    _, line_start, title, matched_alias = best_match
    return LocatedNode(
        chapter_id=chapter_id,
        priority=priority,
        reason=reason,
        line_start=line_start,
        title=title,
        matched_alias=matched_alias,
        located_in_pass=pass_name,
    )


def infer_company(lines: list[str]) -> str:
    for _, line in non_empty_lines(lines, 0, 40):
        if "股份有限公司" in line:
            return line.replace("全文", "").strip()
    return ""


def infer_ticker_and_year(report_path: Path, lines: list[str]) -> tuple[str, int | None]:
    stem = report_path.stem
    ticker_match = re.search(r"(\d{6})", stem)
    ticker = ticker_match.group(1) if ticker_match else ""

    year_match = re.findall(r"(20\d{2})", stem)
    if year_match:
        return ticker, int(year_match[-1])

    for _, line in non_empty_lines(lines, 0, 20):
        inline_year = re.search(r"(20\d{2})\s*年年度报告", line)
        if inline_year:
            return ticker, int(inline_year.group(1))

    return ticker, None


def default_output_path(report_path: Path, ticker: str, year: int | None) -> Path:
    indexes_dir = report_path.parent / "indexes"
    if report_path.parent.name == "annual_report":
        indexes_dir = report_path.parent / "indexes"
    elif report_path.parent.parent.name == "annual_report":
        indexes_dir = report_path.parent.parent / "indexes"
    elif report_path.parent.name.isdigit() and report_path.parent.parent.name == "2_markdown":
        indexes_dir = report_path.parent / "indexes"
    elif report_path.parent.name == "2_markdown":
        report_root = report_path.parent.parent
        indexes_dir = report_root / "4_output" / "indexes"
    if ticker and year:
        return indexes_dir / f"{ticker}_{year}.sections.json"
    return indexes_dir / f"{report_path.stem}.sections.json"


def report_file_value(report_path: Path) -> str:
    parts = list(report_path.parts)
    if "annual_report" in parts:
        start = parts.index("annual_report")
        return str(Path(*parts[start:]))
    if "data" in parts and "reports" in parts:
        start = parts.index("data")
        return str(Path(*parts[start:]))
    return str(report_path)


def classify_title(title: str, rules: list[dict], default_priority: str, default_reason: str) -> tuple[str, str]:
    normalized_title = normalize(strip_heading_prefix(title))
    for rule in rules:
        if any(normalize(keyword) in normalized_title for keyword in rule["keywords"]):
            return rule["priority"], rule["reason"]
    return default_priority, default_reason


def top_level_aliases(entry: dict) -> list[str]:
    return [
        entry["title"],
        f"{entry['prefix']} {entry['name']}",
        f"{entry['prefix']}{entry['name']}",
        entry["name"],
    ]


def build_top_level_specs(toc_entries: list[dict]) -> tuple[list[TopLevelSpec], dict | None]:
    specs: list[TopLevelSpec] = []
    financial_entry: dict | None = None
    for entry in toc_entries:
        if "财务报告" in entry["title"] or "财务会计报告" in entry["title"]:
            financial_entry = entry
            continue
        priority, reason = classify_title(entry["name"], TOP_LEVEL_RULES, "P2", "用于按目录章节定向回查")
        order = entry.get("order") or len(specs) + 1
        specs.append(
            TopLevelSpec(
                chapter_id=f"chapter_{order:02d}",
                aliases=top_level_aliases(entry),
                priority=priority,
                reason=reason,
                toc_title=entry["title"],
                toc_name=entry["name"],
                toc_prefix=entry["prefix"],
                order=order,
            )
        )
    return specs, financial_entry


def assign_top_level_line_ends(nodes: list[LocatedNode], total_lines: int) -> None:
    nodes.sort(key=lambda item: item.line_start)
    for index, node in enumerate(nodes):
        next_start = nodes[index + 1].line_start if index < len(nodes) - 1 else total_lines + 1
        node.line_end = max(node.line_start, next_start - 1)


def parse_cn_child_heading(lines: list[str], start_index: int, end_line: int) -> tuple[int, str, int] | None:
    if start_index + 1 > end_line:
        return None
    first = lines[start_index].strip()
    if not first:
        return None
    if PAGE_HEADER_PATTERN.match(first):
        return None
    if "|" in first or len(first) > 80:
        return None

    match = CN_CHILD_HEADING_PATTERN.match(first)
    if match:
        return start_index + 1, first, 1

    if not re.match(r"^[一二三四五六七八九十百]+、", first):
        return None

    pieces: list[str] = []
    max_index = min(len(lines), start_index + 3, end_line)
    for index in range(start_index, max_index):
        piece = lines[index].strip()
        if not piece:
            if pieces:
                break
            continue
        if PAGE_HEADER_PATTERN.match(piece) or "|" in piece:
            break
        if index > start_index and len(piece) > 24:
            break
        pieces.append(piece)
        joined = "".join(pieces)
        if len(joined) > 80:
            break
        if CN_CHILD_HEADING_PATTERN.match(joined):
            return start_index + 1, joined, index - start_index + 1

    return None


def extract_chapter_children(parent: LocatedNode, lines: list[str]) -> list[ChapterNode]:
    children: list[ChapterNode] = []
    consumed_until = -1
    child_index = 1

    for index in range(parent.line_start, parent.line_end):
        zero_based = index - 1
        if zero_based <= consumed_until:
            continue
        parsed = parse_cn_child_heading(lines, zero_based, parent.line_end)
        if not parsed:
            continue
        line_start, title, consumed_lines = parsed
        if line_start <= parent.line_start:
            continue
        priority, reason = classify_title(
            title,
            CHAPTER_CHILD_RULES,
            parent.priority,
            f"{strip_heading_prefix(parent.title)}章节内小节，便于定向回查",
        )
        children.append(
            ChapterNode(
                chapter_id=f"{parent.chapter_id}_item_{child_index:02d}",
                title=title,
                line_start=line_start,
                line_end=0,
                priority=priority,
                reason=reason,
            )
        )
        child_index += 1
        consumed_until = zero_based + consumed_lines - 1

    for index, child in enumerate(children):
        next_start = children[index + 1].line_start if index < len(children) - 1 else parent.line_end + 1
        child.line_end = max(child.line_start, next_start - 1)

    return children


def locate_note_children(lines: list[str], notes_start: int, search_end: int) -> tuple[list[ChapterNode], int]:
    children: list[ChapterNode] = []
    stop_line = search_end

    for index in range(notes_start + 1, min(len(lines), search_end) + 1):
        stripped = lines[index - 1].strip()
        if not stripped:
            continue
        if line_looks_like_peer_heading(stripped):
            stop_line = index - 1
            break
        parsed = parse_note_item_heading(stripped)
        if not parsed:
            continue
        item_no, normalized_title, display_title = parsed
        if children and children[-1].line_start == index:
            continue
        children.append(
            ChapterNode(
                chapter_id=f"financial_report_notes_item_{item_no}",
                title=display_title,
                line_start=index,
                line_end=0,
                priority="P0",
                reason=f"合并报表附注中的一层科目“{normalized_title}”，便于按科目定向回查",
            )
        )

    parent_end = max(notes_start, stop_line)
    for idx, child in enumerate(children):
        next_start = children[idx + 1].line_start if idx < len(children) - 1 else parent_end + 1
        child.line_end = max(child.line_start, next_start - 1)

    return children, parent_end


def locate_financial_report_nodes(lines: list[str], toc_start: int, toc_end: int, finance_entry: dict | None) -> tuple[list[LocatedNode], list[str]]:
    if finance_entry is None:
        return [], ["financial_report"]

    finance_aliases = top_level_aliases(finance_entry)
    finance_root = locate_node(
        lines,
        chapter_id="financial_report_root",
        aliases=finance_aliases,
        priority="P0",
        reason="财务报告总入口，仅用于限定后续关键条目的搜索范围",
        toc_start=toc_start,
        toc_end=toc_end,
    )
    if finance_root is None:
        return [], ["financial_report"]

    located: list[LocatedNode] = []
    missing: list[str] = []
    for spec in FINANCIAL_REPORT_SPECS:
        found = locate_node(
            lines,
            chapter_id=spec["chapter_id"],
            aliases=spec["aliases"],
            priority=spec["priority"],
            reason=spec["reason"],
            toc_start=toc_start,
            toc_end=toc_end,
            search_start=finance_root.line_start,
            search_end=len(lines),
        )
        if found is None:
            missing.append(spec["chapter_id"])
            continue
        found.title = f"财务报告-{strip_heading_prefix(found.title)}"
        located.append(found)

    return located, missing


def build_index(report_path: Path) -> tuple[dict, dict]:
    lines = report_path.read_text(encoding="utf-8").splitlines()
    company = infer_company(lines)
    ticker, year = infer_ticker_and_year(report_path, lines)
    toc_start, toc_end, toc_entries = detect_toc(lines)

    top_level_specs, financial_entry = build_top_level_specs(toc_entries)
    top_level_nodes: list[LocatedNode] = []
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

    financial_nodes, missing_financial = locate_financial_report_nodes(lines, toc_start, toc_end, financial_entry)
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
    parser = argparse.ArgumentParser(description="Generate a hierarchical annual report chapter index without reading the full report into model context.")
    parser.add_argument("report_path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    output_data, summary = build_index(args.report_path)
    errors = validate_structure(output_data)

    output_path = args.output or default_output_path(args.report_path, output_data.get("ticker", ""), output_data.get("year"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2 if args.pretty else None),
        encoding="utf-8",
    )

    print(json.dumps({"output_path": str(output_path), "summary": summary, "validation_errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
