"""Subagent 用的安全文件写入工具。"""

from __future__ import annotations

from .base import BaseTool
from .file_scope_policy import FileScopePolicy


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "向 data/ 目录写入文本内容；相对路径写入 data/ 下，仅文件名默认写入 data/tmp/。"
    risk_level = 1

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
                        "description": "要写入的授权输出文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的文本内容",
                    },
                    "append": {
                        "type": "boolean",
                        "description": "是否追加到文件末尾，默认 false 表示覆盖",
                    },
                },
                "required": ["path", "content"],
            },
        }

    async def run(self, path: str, content: str, append: bool = False) -> str:
        file_path = self.scope.resolve_write_path(path)
        mode = "a" if append else "w"
        with file_path.open(mode, encoding="utf-8") as f:
            f.write(content)
        action = "追加" if append else "写入"
        return f"已{action}文件: {self.scope._to_rel(file_path)} ({len(content)} 字符)"
