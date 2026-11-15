from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...config import ROOT_DIR
from ..skills.script_runner import run_python_entry
from .base import BaseTool
from .file_scope_policy import FileScopePolicy


class RunPythonScriptTool(BaseTool):
    """专用 Python 脚本执行工具：仅允许运行已启用技能目录下的 .py 文件。"""

    name = "run_python_script"
    description = (
        "执行已启用技能目录中的 Python 脚本（项目根 cwd）。"
        "优先于 run_command 运行 extensions/skills/**/scripts/*.py；"
        "支持 argv 位置参数/子命令、kwargs 旗标、可选 stdin。"
        "脚本写入被限制在 data/ 内；仅当专用工具无法覆盖时再使用 run_command。"
    )
    risk_level = 2

    def __init__(
        self,
        project_root: str | Path | None = None,
        allowed_skill_names: list[str] | None = None,
        scope: FileScopePolicy | None = None,
    ):
        self.project_root = Path(project_root or ROOT_DIR).resolve()
        self.allowed_skill_names = list(allowed_skill_names or [])
        self.scope = scope

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "script_path": {
                        "type": "string",
                        "description": (
                            "要执行的 Python 脚本相对路径，"
                            "仅允许 extensions/skills/<skill_name>/ 下的 .py 文件"
                        ),
                    },
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "传给脚本的位置参数/子命令列表，例如 "
                            "[\"data/reports/a.pdf\", \"-o\", \"data/reports/a.md\"] "
                            "或 [\"auto\", \"file.md\", \"out_dir\"]"
                        ),
                    },
                    "kwargs": {
                        "type": "object",
                        "description": (
                            "旗标参数对象；会转为 --flag value 追加在 argv 后。"
                            "若未提供 stdin，同时以 JSON 写入 stdin"
                        ),
                    },
                    "stdin": {
                        "type": "string",
                        "description": "可选标准输入文本（如 TSV 行）；提供后不再自动写入 kwargs JSON",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "脚本超时时间（秒），默认 120，最大 120",
                    },
                },
                "required": ["script_path"],
            },
        }

    def _resolve_script_path(self, script_path: str) -> tuple[Path, Path]:
        if not isinstance(script_path, str) or not script_path.strip():
            raise ValueError("script_path 必须是非空字符串")

        raw_path = Path(script_path.strip())
        if raw_path.is_absolute():
            raise ValueError("只允许使用项目相对路径，不允许绝对路径")

        resolved = (self.project_root / raw_path).resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(f"script_path 不允许逃逸项目目录: {script_path}") from exc

        if resolved.suffix != ".py":
            raise ValueError("只允许执行 .py 文件")
        if not resolved.exists() or not resolved.is_file():
            raise ValueError(f"脚本不存在: {script_path}")

        for skill_name in self.allowed_skill_names:
            skill_root = (
                self.project_root / "extensions" / "skills" / skill_name
            ).resolve()
            try:
                resolved.relative_to(skill_root)
                return resolved, skill_root
            except ValueError:
                continue

        if not self.allowed_skill_names:
            raise ValueError("当前 Agent 未启用任何技能，无法执行技能脚本")
        allowed_roots = ", ".join(
            f"extensions/skills/{name}/" for name in self.allowed_skill_names
        )
        raise ValueError(
            "脚本不在已启用技能目录内: "
            f"{script_path}。当前允许目录: {allowed_roots}"
        )

    @staticmethod
    def _normalize_kwargs(kwargs: dict[str, Any] | None) -> dict[str, Any]:
        if kwargs is None:
            return {}
        if not isinstance(kwargs, dict):
            raise ValueError("kwargs 必须是对象")
        try:
            json.dumps(kwargs, ensure_ascii=False)
        except TypeError as exc:
            raise ValueError("kwargs 必须可序列化为 JSON") from exc
        return kwargs

    @staticmethod
    def _normalize_argv(argv: list[str] | None) -> list[str]:
        if argv is None:
            return []
        if not isinstance(argv, list):
            raise ValueError("argv 必须是字符串数组")
        out: list[str] = []
        for item in argv:
            if not isinstance(item, str):
                raise ValueError("argv 的每一项必须是字符串")
            out.append(item)
        return out

    async def run(
        self,
        script_path: str,
        argv: list[str] | None = None,
        kwargs: dict[str, Any] | None = None,
        stdin: str | None = None,
        timeout_seconds: int = 120,
    ) -> str:
        try:
            normalized_argv = self._normalize_argv(argv)
            normalized_kwargs = self._normalize_kwargs(kwargs)
            timeout_seconds = max(1, min(int(timeout_seconds or 120), 120))
            resolved_script, skill_root = self._resolve_script_path(script_path)
            result = await run_python_entry(
                project_root=self.project_root,
                entry_path=resolved_script,
                skill_root=skill_root,
                argv=normalized_argv,
                kwargs=normalized_kwargs,
                stdin=stdin,
                timeout_seconds=timeout_seconds,
            )
            return result or "(no output)"
        except Exception as e:
            return f"Python 脚本执行失败: {e}"
