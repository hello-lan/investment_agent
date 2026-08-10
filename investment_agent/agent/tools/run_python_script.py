from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..skills.script_runner import run_python_entry
from .base import BaseTool


class RunPythonScriptTool(BaseTool):
    """专用 Python 脚本执行工具：仅允许运行已启用技能目录下的 .py 文件。"""

    name = "run_python_script"
    description = (
        "执行已启用技能目录中的 Python 脚本。"
        "适用于运行 extensions/skills/** 下的脚本，"
        "比 run_command 更结构化、更安全。"
    )
    risk_level = 2

    def __init__(
        self,
        project_root: str | Path = ".",
        allowed_skill_names: list[str] | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.allowed_skill_names = list(allowed_skill_names or [])

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
                        "description": "要执行的 Python 脚本相对路径，仅允许 extensions/skills/<skill_name>/ 下的 .py 文件",
                    },
                    "kwargs": {
                        "type": "object",
                        "description": "传给脚本的参数对象；会同时以 CLI 参数和 stdin JSON 形式传递",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "脚本超时时间（秒），默认 20，最大 120",
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

    async def run(
        self,
        script_path: str,
        kwargs: dict[str, Any] | None = None,
        timeout_seconds: int = 20,
    ) -> str:
        try:
            normalized_kwargs = self._normalize_kwargs(kwargs)
            timeout_seconds = max(1, min(int(timeout_seconds or 20), 120))
            resolved_script, skill_root = self._resolve_script_path(script_path)
            result = await run_python_entry(
                base_dir=skill_root,
                entry_path=resolved_script,
                kwargs=normalized_kwargs,
                timeout_seconds=timeout_seconds,
            )
            return result or "(no output)"
        except Exception as e:
            return f"Python 脚本执行失败: {e}"
