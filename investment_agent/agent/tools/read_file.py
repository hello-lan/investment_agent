"""Subagent 用的安全文件读取工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .base import BaseTool
from .file_scope_policy import FileScopePolicy
from .result_formatter import format_tool_result


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "读取授权范围内的文本文件，可按行范围截取。"
    risk_level = 0
    trim_max_chars = 15000

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
                        "description": "要读取的授权文件路径",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "起始行号（从 1 开始），默认 1",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "最多读取多少行，默认 500",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "最多返回多少字符，默认 15000",
                    },
                },
                "required": ["path"],
            },
        }

    def _iter_lines(self, file_path: Path) -> Iterator[str]:
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line.rstrip("\r\n")

    async def run(
        self,
        path: str,
        start_line: int = 1,
        max_lines: int = 500,
        max_chars: int = 15000,
    ) -> str:
        file_path = self.scope.resolve_read_path(path, allow_dir=False)
        start_line = max(1, start_line or 1)
        max_lines = max(1, min(max_lines or 500, 1000))
        max_chars = max(200, min(max_chars or 15000, 50000))

        body_lines: list[str] = []
        body_len = 0
        partial_last_line = False
        has_more = False
        truncated_by = "none"
        total_lines: int | None = None
        returned_end_line: int | None = None
        next_start_line: int | None = None
        last_seen_line = 0

        line_iter = enumerate(self._iter_lines(file_path), start=1)
        for line_no, line in line_iter:
            last_seen_line = line_no
            if line_no < start_line:
                continue

            numbered = f"{line_no}\t{line}"
            piece_len = len(numbered) + (1 if body_lines else 0)

            if not body_lines and len(numbered) > max_chars:
                body_lines.append(numbered[:max_chars])
                body_len = len(body_lines[0])
                partial_last_line = True
                has_more = True
                truncated_by = "max_chars"
                returned_end_line = line_no
                next_start_line = line_no
                break

            if body_lines and body_len + piece_len > max_chars:
                has_more = True
                truncated_by = "max_chars"
                next_start_line = line_no
                break

            body_lines.append(numbered)
            body_len += piece_len
            returned_end_line = line_no

            if len(body_lines) >= max_lines:
                peek = next(line_iter, None)
                if peek is None:
                    total_lines = line_no
                else:
                    has_more = True
                    truncated_by = "max_lines"
                    next_start_line = peek[0]
                break
        else:
            total_lines = last_seen_line

        returned_lines = len(body_lines)
        returned_start_line = start_line if returned_lines else None

        if body_lines:
            body = "\n".join(body_lines)
        elif total_lines == 0:
            body = "(空文件)"
        elif total_lines is not None and start_line > total_lines:
            body = "(起始行超出文件末尾)"
        else:
            body = "(无内容)"

        return format_tool_result(
            self.name,
            body,
            path=self.scope._to_rel(file_path),
            start_line=start_line,
            returned_start_line=returned_start_line,
            returned_end_line=returned_end_line,
            returned_lines=returned_lines,
            total_lines=total_lines,
            complete=not has_more,
            has_more=has_more,
            next_start_line=next_start_line,
            truncated_by=truncated_by,
            partial_last_line=partial_last_line,
        )
