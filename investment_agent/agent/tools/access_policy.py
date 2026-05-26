"""run_command 文件系统访问策略（deny list 模式）。

从 shell 命令中提取路径 token，仅检查是否命中禁止目录。
不在黑名单中的路径一律放行，避免对命令内容的误判。

安全模型：
- investment_agent/ → 读写全拒（项目源码）
- extensions/ → 全部拒绝，已启用技能的子目录除外（只读）
- 其他路径 → 放行
"""

from __future__ import annotations

import os
import re

# 系统设备路径白名单（允许访问，不检查 PROJECT_ROOT 限制）
_SYSTEM_PATHS_UNIX = {"/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr"}
_SYSTEM_PATHS_WINDOWS = {"NUL", "CON", "PRN", "AUX"}

# ── 安全不变量（硬编码，不可由 Agent 配置覆盖）──

# 顶层目录名：读写全拒
_HARD_DENY_TOP_DIRS = {"investment_agent"}

# extensions/ 下允许只读的子目录模式：extensions/skills/{name}/
# 其中 {name} 必须在 Agent 的 _skill_names 中


class AccessPolicy:
    """run_command 的文件系统访问策略（deny list 模式）。

    只检查命令中引用的路径是否命中禁止目录。
    未命中黑名单的路径一律放行。
    """

    def __init__(self, project_root: str, skill_names: list[str] | None = None):
        self.project_root = project_root
        self._skill_names: list[str] = skill_names or []
        self._unrestricted = False

    @property
    def has_skills(self) -> bool:
        return bool(self._skill_names)

    def describe_mode(self) -> str:
        """返回当前权限模式的简短描述。"""
        if not self._skill_names:
            return "无技能(仅data目录)"
        return f"有技能({', '.join(self._skill_names)})"

    def prompt_section(self) -> str:
        """生成 system prompt 注入文本，告知 Agent 文件访问边界。"""
        if self._unrestricted:
            return ""

        lines = ["\n\n## run_command 文件访问规则\n"]
        lines.append("### 禁止访问")
        lines.append("- `investment_agent/` — 项目源码，禁止读写")
        lines.append("- `extensions/` — 禁止访问，已启用的技能目录除外（只读）")
        lines.append("")
        lines.append("### 允许访问")
        lines.append("- `data/` — 读写")
        lines.append("- `.venv/` — 只读")
        if self._skill_names:
            for name in self._skill_names:
                lines.append(f"- `extensions/skills/{name}/` — 只读")
        lines.append("- 其他目录不受限制")
        lines.append(
            "\n**不要尝试访问被禁止的目录**，否则会收到权限拒绝错误并浪费执行步骤。"
        )
        return "\n".join(lines)

    def check(self, command: str) -> str | None:
        """检查命令中的路径引用是否命中禁止目录。

        返回 None 表示允许，否则返回错误信息。
        """
        if self._unrestricted:
            return None

        # 拆分命令（考虑 | ; && ||）
        tokens = (
            command.replace("|", " ")
                   .replace(";", " ")
                   .replace("&&", " ")
                   .replace("||", " ")
                   .split()
        )

        for token in tokens:
            if not self._is_path_like(token):
                continue

            # 剥离尾部标点（Python dict/list 字面量残留：'path', "path", path;)
            token = token.rstrip(",;:)]}")

            # 剥离外层引号（shell/Python 字符串字面量：'path', "path"）
            if (
                len(token) >= 2
                and token[0] == token[-1]
                and token[0] in ('"', "'")
            ):
                token = token[1:-1]

            # 系统设备路径白名单检查（/dev/null, NUL 等）
            clean_token = token.lstrip("0123456789>&")
            if (
                clean_token in _SYSTEM_PATHS_UNIX
                or clean_token.upper() in _SYSTEM_PATHS_WINDOWS
                or token in _SYSTEM_PATHS_UNIX
                or token.upper() in _SYSTEM_PATHS_WINDOWS
            ):
                continue

            resolved = os.path.normpath(
                os.path.join(self.project_root, token)
            )

            # 防止路径逃逸：resolved 必须是 project_root 本身或其子目录
            if (
                resolved != self.project_root
                and not resolved.startswith(self.project_root + os.sep)
            ):
                return f"权限拒绝: 路径 '{token}' 逃逸出项目目录"

            rel = os.path.relpath(resolved, self.project_root)

            # 项目根目录引用（cd /project/root, ls . 等）视为 no-op，放行
            if rel == ".":
                continue

            # ── deny list：只检查是否命中禁止目录 ──
            error = self._check_deny_list(rel, command, token)
            if error:
                return error

        return None  # 未命中任何禁止规则，放行

    # ── deny list 核心逻辑 ─────────────────────────────────────────────

    def _check_deny_list(
        self, rel_path: str, command: str, path_token: str
    ) -> str | None:
        """检查路径是否命中禁止目录。返回错误信息或 None。"""
        rel_parts = rel_path.replace("\\", "/").split("/")

        # 硬拒绝：investment_agent/ — 读写全拒
        if rel_parts[0] in _HARD_DENY_TOP_DIRS:
            return f"权限拒绝: 不允许访问项目源码目录 '{rel_path}'"

        # extensions/ 规则
        if rel_parts[0] == "extensions":
            # extensions/skills/{已启用技能}/ — 只读
            if (
                len(rel_parts) >= 3
                and rel_parts[1] == "skills"
                and rel_parts[2] in self._skill_names
            ):
                if self._looks_like_write(command, path_token):
                    return (
                        f"权限拒绝: 技能目录 '{rel_path}' "
                        f"为只读，不允许写入"
                    )
                return None  # 已启用技能目录的读操作，允许

            # 其他 extensions/ — 全部拒绝
            return (
                f"权限拒绝: 不允许访问 '{rel_path}'"
                f"（extensions/ 仅限已启用的技能目录）"
            )

        return None  # 不在禁止目录中，放行

    # ── 启发式判断 ────────────────────────────────────────────────────

    def _is_path_like(self, token: str) -> bool:
        """启发式判断 token 是否为文件路径。"""
        if token.startswith("-"):
            return False

        # 裸 "/" 不是合法路径引用（通常是文本中的除号或字符串片段）
        if token == "/":
            return False

        # ── 快速过滤：明显不是路径的 token ──
        # CJK 字符（本项目所有文件路径均为英文/数字/下划线/连字符）
        if re.search(r"[一-鿿㐀-䶿]", token):
            return False
        # markdown 格式标记（**bold**, __italic__）
        if "**" in token or "__" in token:
            return False
        # 全角括号（中文文本特征）
        if "（" in token or "）" in token:
            return False

        # 跳过含不匹配引号或括号的 token（大概率是代码片段，非 shell 路径）
        if self._looks_like_code(token):
            return False

        if "/" in token or ".." in token:
            return True
        abs_path = os.path.join(self.project_root, token)
        return os.path.exists(abs_path)

    def _looks_like_code(self, token: str) -> bool:
        """检测 token 是否像 Python 代码片段（而非 shell 路径）。

        heredoc 内的 Python 代码被 split() 拆分后，会产生类似：
          sqlite3.connect('data/agent.db')
          os.path.expanduser('~/.tushare/token')
          ['/home/.../python3','
        的片段。检测方法：
        1. 不匹配的引号 + 不匹配的括号 → 代码
        2. 括号内含引号（函数调用传字符串参数）→ 代码
        3. 不匹配括号 → 代码
        """
        has_quotes = "'" in token or '"' in token

        # 不匹配括号（即使引号匹配也是代码片段）
        if token.count("[") != token.count("]"):
            return True
        if token.count("(") != token.count(")") and has_quotes:
            return True

        if not has_quotes:
            return False

        # 引号不匹配 → 代码片段
        if token.count("'") % 2 != 0 or token.count('"') % 2 != 0:
            return True

        # 括号内含引号：func('path') 或 func("path") 模式 → 代码
        if re.search(r"\([^)]*['\"]", token) or re.search(
            r"\[[^\]]*['\"]", token
        ):
            return True

        return False

    def _looks_like_write(self, command: str, path_token: str) -> bool:
        """启发式判断命令是否对路径执行写操作。"""
        write_indicators = [
            f"rm {path_token}",
            f"rm -rf {path_token}",
            f"rm -f {path_token}",
            "mv ",
            "cp ",
            f"> {path_token}",
            f">> {path_token}",
            f"tee {path_token}",
            "sed -i",
            "sed --in-place",
            "mkdir ",
        ]
        cmd_lower = command.lower()
        return any(ind in cmd_lower for ind in write_indicators)

    # ── 工厂方法 ──────────────────────────────────────────────────────

    @classmethod
    def for_agent(cls, project_root: str, skills: list[str]) -> AccessPolicy:
        return cls(project_root, skill_names=list(skills))

    @classmethod
    def unrestricted(cls) -> AccessPolicy:
        """不限制（向后兼容，用于未设置 policy 的场景）。"""
        policy = cls("", skill_names=[])
        policy._unrestricted = True
        return policy
