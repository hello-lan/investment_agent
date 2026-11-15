"""Subagent / 主 Agent 文件作用域策略。"""

from __future__ import annotations

from pathlib import Path

from ...config import ROOT_DIR


class FileScopePolicy:
    """约束 Agent 可读写的文件范围。"""

    _FORBIDDEN_TOP_DIRS = {
        "investment_agent",
        "extensions",
        ".git",
        ".claude",
        ".venv",
        ".venv_2",
        "__pycache__",
    }
    _FORBIDDEN_PATHS = {
        "data/agent.db",
        "daemon.json",
    }
    _MAIN_AGENT_OPTIONAL_TARGETS = ("output", "docs")

    def __init__(
        self,
        project_root: str | Path,
        targets: list[str | Path],
        workspace_root: str | Path,
        output_path: str | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.data_root = self.project_root / "data"
        self.default_write_root = self.data_root / "tmp"
        self.workspace_root = self._resolve_within_data(workspace_root, default_to_tmp=False)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.default_write_root.mkdir(parents=True, exist_ok=True)
        self.output_path = (
            self._validate_write_path(output_path)
            if output_path else None
        )

        if not targets:
            raise ValueError("Agent 必须提供至少一个 targets 路径")

        self.read_targets = [
            self._validate_allowed_path(path, purpose="read")
            for path in targets
        ]

    @classmethod
    def for_main_agent(cls, project_root: str | Path = ROOT_DIR) -> "FileScopePolicy":
        """创建主 Agent 的宽范围文件作用域。"""
        project_root = Path(project_root).resolve()
        data_root = project_root / "data"
        data_root.mkdir(parents=True, exist_ok=True)

        targets = ["data"]
        for rel in cls._MAIN_AGENT_OPTIONAL_TARGETS:
            if (project_root / rel).exists():
                targets.append(rel)

        return cls(
            project_root=project_root,
            targets=targets,
            workspace_root="data/tmp/main-agent",
        )

    @classmethod
    def for_subagent(
        cls,
        *,
        project_root: str | Path = ROOT_DIR,
        targets: list[str],
        workspace_root: str | Path,
        output_path: str | None = None,
    ) -> "FileScopePolicy":
        """创建子 Agent 的任务级窄作用域。"""
        return cls(
            project_root=project_root,
            targets=targets,
            workspace_root=workspace_root,
            output_path=output_path,
        )

    def prompt_section(self) -> str:
        lines = ["\n\n## 文件作用域规则\n"]
        lines.append("### 允许读取")
        for path in self.read_targets:
            lines.append(f"- `{self._to_rel(path)}`")
        lines.append("")
        lines.append("### 允许写入")
        lines.append(f"- `{self._to_rel(self.data_root)}/` 及其子目录")
        lines.append(f"- 仅提供文件名时，默认写入 `{self._to_rel(self.default_write_root)}/`")
        if self.output_path:
            lines.append(f"- 推荐输出路径：`{self._to_rel(self.output_path)}`")
        lines.append(f"- 子Agent工作区：`{self._to_rel(self.workspace_root)}/`")
        lines.append("")
        lines.append("### 读取结果说明")
        lines.append("- `read_file` / `list_files` / `search_text` 会先返回 `[result]` 元信息头，再给出正文")
        lines.append("- 如头部出现 `complete=false` 或 `has_more=true`，表示结果不完整，不能据此声称已覆盖全部内容")
        lines.append("- 继续读取时，优先使用头部提供的 `next_start_line` 或 `next_offset`")
        lines.append("")
        lines.append("### 禁止访问")
        lines.append("- `investment_agent/` 项目源码")
        lines.append("- `extensions/` 技能目录")
        lines.append("- `.git/`、`.claude/`、虚拟环境目录、数据库文件")
        lines.append("- 任何未列入 targets 的读取路径")
        return "\n".join(lines)

    def main_agent_prompt_section(self) -> str:
        lines = ["\n\n## 安全文件工具访问规则\n"]
        lines.append("### 可读取范围")
        for path in self.read_targets:
            label = self._to_rel(path)
            suffix = "/" if path.is_dir() else ""
            lines.append(f"- `{label}{suffix}`")
        lines.append("")
        lines.append("### 可写入范围")
        lines.append(f"- 仅允许写入 `{self._to_rel(self.data_root)}/` 及其子目录")
        lines.append(f"- 仅提供文件名时，默认写入 `{self._to_rel(self.default_write_root)}/`")
        lines.append("")
        lines.append("### 读取结果说明")
        lines.append("- `read_file` / `list_files` / `search_text` 会先返回 `[result]` 元信息头，再给出正文")
        lines.append("- 如头部出现 `complete=false` 或 `has_more=true`，表示结果不完整，不能据此声称已覆盖全部内容")
        lines.append("- 继续读取时，优先使用头部提供的 `next_start_line` 或 `next_offset`")
        lines.append("")
        lines.append("### 禁止访问")
        lines.append("- `investment_agent/` 项目源码")
        lines.append("- `extensions/` 技能目录")
        lines.append("- `.git/`、`.claude/`、虚拟环境目录、数据库文件")
        lines.append("- 任何未列入可读取范围的路径")
        return "\n".join(lines)

    def read_roots(self) -> list[Path]:
        roots: list[Path] = []
        for path in self.read_targets:
            roots.append(path if path.is_dir() else path.parent)
        return roots

    def resolve_read_path(self, raw_path: str, *, allow_dir: bool = False) -> Path:
        path = self._resolve_within_project(raw_path)
        if not path.exists():
            raise ValueError(f"路径不存在: {raw_path}")
        self._reject_forbidden(path)
        if path.is_dir() and not allow_dir:
            raise ValueError(f"需要文件路径，收到目录: {raw_path}")
        if not self._is_within_read_scope(path):
            raise ValueError(f"路径未授权读取: {raw_path}")
        return path

    def resolve_write_path(self, raw_path: str) -> Path:
        path = self._resolve_within_data(raw_path, default_to_tmp=True)
        self._reject_forbidden(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def iter_search_files(self, base_path: str | None = None) -> list[Path]:
        files: list[Path] = []
        if base_path:
            resolved = self.resolve_read_path(base_path, allow_dir=True)
            candidates = [resolved]
        else:
            candidates = list(self.read_targets)

        for candidate in candidates:
            if candidate.is_file():
                files.append(candidate)
                continue
            files.extend(
                p for p in candidate.rglob("*")
                if p.is_file() and self._is_within_read_scope(p)
            )
        return sorted(set(files))

    def _validate_allowed_path(self, raw_path: str | Path, *, purpose: str) -> Path:
        path = self._resolve_within_project(raw_path)
        self._reject_forbidden(path)
        if purpose == "read" and not path.exists():
            raise ValueError(f"targets 路径不存在: {raw_path}")
        return path

    def _validate_write_path(self, raw_path: str) -> Path:
        path = self._resolve_within_data(raw_path, default_to_tmp=True)
        self._reject_forbidden(path)
        return path

    def _reject_forbidden(self, path: Path) -> None:
        rel = self._to_rel(path)
        if rel == ".":
            return
        top = rel.split("/", 1)[0]
        if top in self._FORBIDDEN_TOP_DIRS:
            raise ValueError(f"禁止访问敏感目录: {rel}")
        if rel in self._FORBIDDEN_PATHS:
            raise ValueError(f"禁止访问敏感文件: {rel}")

    def _is_within_read_scope(self, path: Path) -> bool:
        for target in self.read_targets:
            if path == target:
                return True
            if target.is_dir() and target in path.parents:
                return True
            if target.is_file() and path == target:
                return True
        return False

    def _resolve_within_project(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.project_root / path
        resolved = path.resolve()
        if resolved != self.project_root and self.project_root not in resolved.parents:
            raise ValueError(f"路径逃逸出项目目录: {raw_path}")
        return resolved

    def _resolve_within_data(
        self,
        raw_path: str | Path,
        *,
        default_to_tmp: bool,
    ) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            resolved = path.resolve()
        else:
            if path.parent == Path("."):
                base = self.default_write_root if default_to_tmp else self.data_root
            elif path.parts and path.parts[0] == "data":
                base = self.project_root
            else:
                base = self.data_root
            resolved = (base / path).resolve()

        if resolved != self.data_root and self.data_root not in resolved.parents:
            raise ValueError(f"写入路径必须位于 data 目录内: {raw_path}")
        return resolved

    def _to_rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.project_root).as_posix()
        except ValueError:
            return path.as_posix()
