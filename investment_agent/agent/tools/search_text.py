"""Subagent 用的安全文本搜索工具。"""

from __future__ import annotations

import re
from fnmatch import fnmatch

from .base import BaseTool
from .file_scope_policy import FileScopePolicy
from .result_formatter import format_tool_result


class SearchTextTool(BaseTool):
    name = "search_text"
    description = "在授权范围内搜索文本，支持关键词或正则，并返回匹配上下文。"
    risk_level = 0
    trim_max_chars = 12000

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
                    "query": {
                        "type": "string",
                        "description": "要搜索的关键词或正则表达式",
                    },
                    "path": {
                        "type": "string",
                        "description": "授权范围内的目录或文件；留空则搜索全部授权 targets",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "文件名过滤模式，如 *.md、*.txt",
                    },
                    "regex": {
                        "type": "boolean",
                        "description": "是否将 query 视为正则表达式",
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "description": "是否忽略大小写，默认 true",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "每个命中前后保留多少行上下文，默认 1",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "命中结果分页偏移量，默认 0",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回多少个命中，默认 50",
                    },
                },
                "required": ["query"],
            },
        }

    async def run(
        self,
        query: str,
        path: str | None = None,
        pattern: str | None = None,
        regex: bool = False,
        ignore_case: bool = True,
        context_lines: int = 1,
        offset: int = 0,
        max_results: int = 50,
    ) -> str:
        flags = re.IGNORECASE if ignore_case else 0
        compiled = re.compile(query if regex else re.escape(query), flags)
        context_lines = max(0, min(context_lines or 1, 10))
        offset = max(0, offset or 0)
        max_results = max(1, min(max_results or 50, 200))

        files = self.scope.iter_search_files(path)
        if pattern:
            files = [p for p in files if fnmatch(p.name, pattern)]

        results: list[str] = []
        skipped = 0
        has_more = False
        searched_files = len(files)

        for file_path in files:
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="utf-8", errors="replace")

            lines = text.splitlines()
            for idx, line in enumerate(lines):
                if not compiled.search(line):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                start = max(0, idx - context_lines)
                end = min(len(lines), idx + context_lines + 1)
                chunk = []
                for i in range(start, end):
                    prefix = ">" if i == idx else " "
                    chunk.append(f"{prefix}{i + 1}\t{lines[i]}")
                results.append(
                    f"## {self.scope._to_rel(file_path)}\n" + "\n".join(chunk)
                )
                if len(results) > max_results:
                    has_more = True
                    break
            if has_more:
                break

        if has_more:
            page = results[:max_results]
        else:
            page = results
        next_offset = offset + len(page) if has_more else None
        truncated_by = "max_results" if has_more else "none"

        if page:
            body = "\n\n".join(page)
        elif offset > 0:
            body = "(无更多结果)"
        else:
            body = "(未找到匹配文本)"

        return format_tool_result(
            self.name,
            body,
            query=query,
            path=path or "(all_targets)",
            pattern=pattern,
            regex=regex,
            ignore_case=ignore_case,
            context_lines=context_lines,
            offset=offset,
            returned_matches=len(page),
            searched_files=searched_files,
            complete=not has_more,
            has_more=has_more,
            next_offset=next_offset,
            truncated_by=truncated_by,
        )
