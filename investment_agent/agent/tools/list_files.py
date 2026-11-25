"""Subagent 用的安全文件列举工具。"""

from __future__ import annotations

from fnmatch import fnmatch

from .base import BaseTool
from .file_scope_policy import FileScopePolicy
from .result_formatter import format_tool_result


def _normalize_patterns(pattern: str | list[str] | None) -> list[str]:
    if pattern is None:
        return []
    if isinstance(pattern, str):
        items = [pattern]
    else:
        items = list(pattern)
    return [p.strip() for p in items if isinstance(p, str) and p.strip()]


def _path_matches(rel: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    path = rel.rstrip("/")
    return any(fnmatch(path, p) for p in patterns)


class ListFilesTool(BaseTool):
    name = "list_files"
    description = (
        "列举授权范围内的文件或目录。支持递归；pattern 对相对路径做 fnmatch"
        "（可 string 或 string[]，多值 OR）。\n"
        "\n"
        "示例：\n"
        '1) path="data/reports/md/600377", pattern="*.md"\n'
        "   → data/reports/md/600377/600377_2024年年度报告_2024.md\n"
        '2) path="data/reports/md/600377", pattern="*2024*年度*"\n'
        "   → …/600377_2024年年度报告_2024.md（路径需同时含 2024 与「年度」）\n"
        '3) path="data/reports/md/600377", pattern=["*2023*","*2024*"]\n'
        "   → 同时列出含 2023 或 2024 的相对路径（多值 OR）"
    )
    risk_level = 0

    def __init__(self, scope: FileScopePolicy):
        self.scope = scope

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要列举的授权目录或文件路径；留空则列举所有授权 targets",
                    },
                    "pattern": {
                        "description": (
                            "相对路径 fnmatch；string 或 string[]（多值 OR）。"
                            '例："*.md"、"*2024*年度*"、["*2023*","*2024*"]'
                        ),
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "是否递归列举子目录",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "分页偏移量，默认 0",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回多少条记录，默认 200",
                    },
                },
            },
        }

    async def run(
        self,
        path: str | None = None,
        pattern: str | list[str] | None = None,
        recursive: bool = True,
        offset: int = 0,
        max_results: int = 200,
    ) -> str:
        offset = max(0, offset or 0)
        max_results = max(1, min(max_results or 200, 500))
        patterns = _normalize_patterns(pattern)

        if path:
            roots = [self.scope.resolve_read_path(path, allow_dir=True)]
        else:
            roots = list(self.scope.read_targets)

        entries: list[str] = []
        for root in roots:
            if root.is_file():
                rel = self.scope._to_rel(root)
                if _path_matches(rel, patterns):
                    entries.append(rel)
                continue

            iterator = root.rglob("*") if recursive else root.iterdir()
            for item in iterator:
                if not self.scope._is_within_read_scope(item):
                    continue
                rel = self.scope._to_rel(item)
                suffix = "/" if item.is_dir() else ""
                if not _path_matches(rel, patterns):
                    continue
                entries.append(rel + suffix)

        entries = sorted(set(entries))
        page = entries[offset: offset + max_results]
        has_more = offset + len(page) < len(entries)
        next_offset = offset + len(page) if has_more else None
        truncated_by = "max_results" if has_more else "none"

        if page:
            body = "\n".join(page)
        elif entries and offset > 0:
            body = "(无更多结果)"
        else:
            body = "(未找到匹配文件)"

        return format_tool_result(
            self.name,
            body,
            path=path or "(all_targets)",
            pattern=patterns if patterns else None,
            recursive=recursive,
            offset=offset,
            returned_entries=len(page),
            total_entries=len(entries),
            complete=not has_more,
            has_more=has_more,
            next_offset=next_offset,
            truncated_by=truncated_by,
        )
