"""run_command 文件系统访问策略。

在 run_command 执行前检查命令中引用的路径，按 zone 规则决定是否允许。
每个 Agent 只能访问自己已配置的技能子目录，未配置的技能完全不可见。
"""

from __future__ import annotations

import os
import re
from fnmatch import fnmatch

NONE = 0   # 禁止访问
READ = 1   # 只读
WRITE = 2  # 读写

# 系统设备路径白名单（允许访问，不检查 PROJECT_ROOT 限制）
_SYSTEM_PATHS_UNIX = {"/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr"}
_SYSTEM_PATHS_WINDOWS = {"NUL", "CON", "PRN", "AUX"}


class AccessPolicy:
    """run_command 的文件系统访问策略。"""

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
        lines.append("你只能通过 run_command 访问以下目录：")
        lines.append("- `data/` — 读写（报告、临时文件、数据库等）")
        lines.append("- `.venv/` — 只读（虚拟环境 Python 解释器和已安装包）")

        if self._skill_names:
            for name in self._skill_names:
                lines.append(f"- `extensions/skills/{name}/` — 只读")
        else:
            lines.append("\n禁止访问 `extensions/skills/`、项目源码、配置文件等其他目录。")

        lines.append("\n**不要尝试访问被禁止的目录**，否则会收到权限拒绝错误并浪费执行步骤。")
        return "\n".join(lines)

    def check(self, command: str) -> str | None:
        """检查命令中的路径引用。返回 None 表示允许，否则返回错误信息。"""
        if self._unrestricted:
            return None

        zones = self._build_zones()

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
            # 必须在引号剥离之前执行，否则 'path', 的首尾引号不匹配会跳过剥离
            token = token.rstrip(",;:)]}")

            # 剥离外层引号（shell/Python 字符串字面量：'path', "path"）
            if len(token) >= 2 and token[0] == token[-1] and token[0] in ('"', "'"):
                token = token[1:-1]

            # 系统设备路径白名单检查（/dev/null, NUL 等）
            # 处理 shell 重定向语法：2>/dev/null, >>/dev/null 等
            clean_token = token.lstrip("0123456789>&")
            if (clean_token in _SYSTEM_PATHS_UNIX or
                clean_token.upper() in _SYSTEM_PATHS_WINDOWS or
                token in _SYSTEM_PATHS_UNIX or
                token.upper() in _SYSTEM_PATHS_WINDOWS):
                continue

            resolved = os.path.normpath(os.path.join(self.project_root, token))

            # 防止路径逃逸：resolved 必须是 project_root 本身或其子目录
            if resolved != self.project_root and not resolved.startswith(self.project_root + os.sep):
                return f"权限拒绝: 路径 '{token}' 逃逸出项目目录"

            rel = os.path.relpath(resolved, self.project_root)

            # 项目根目录引用（cd /project/root, ls . 等）视为 no-op，放行
            if rel == ".":
                continue

            level = self._match_zone(rel, zones)

            # 技能目录相对路径 fallback：SKILL.md 中的 CLI 示例通常使用
            # 技能目录相对路径（如 scripts/xxx.py），尝试在允许的技能目录中查找
            if level == NONE and self._skill_names:
                level = self._match_skill_relative_path(token, zones)

            if level == NONE:
                return f"权限拒绝: '{rel}' 不在允许访问范围内"
            if level == READ and self._looks_like_write(command, token):
                return f"权限拒绝: '{rel}' 为只读区域，不允许写入"

        return None

    def _build_zones(self) -> list[tuple[str, int]]:
        """动态构建分区规则。data/ 始终读写，.venv/ 和技能目录只读。"""
        zones: list[tuple[str, int]] = [
            ("data", WRITE),
            ("data/*", WRITE),
            (".venv", READ),
            (".venv/*", READ),
        ]
        for name in self._skill_names:
            skill_prefix = f"extensions/skills/{name}"
            zones.append((skill_prefix, READ))
            zones.append((f"{skill_prefix}/*", READ))
        return zones

    def _is_path_like(self, token: str) -> bool:
        """启发式判断 token 是否为路径。

        额外跳过 Python 代码片段：heredoc 内的 Python 代码被按空格拆分后，
        含 / 的字符串字面量（如 sqlite3.connect('data/agent.db')）会被误判为路径。
        通过检测不匹配的引号/括号来过滤这类代码片段。
        """
        if token.startswith("-"):
            return False

        # 跳过含不匹配引号或括号的 token（大概率是代码片段，非 shell 路径）
        # shell 命令中的合法路径不会出现在不匹配引号内
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
        if re.search(r"\([^)]*['\"]", token) or re.search(r"\[[^\]]*['\"]", token):
            return True

        return False

    def _match_zone(self, rel_path: str, zones: list[tuple[str, int]]) -> int:
        """匹配分区规则，返回权限级别。"""
        for pattern, level in zones:
            if fnmatch(rel_path, pattern):
                return level
        return NONE  # 默认拒绝未匹配路径

    def _match_skill_relative_path(self, token: str, zones: list[tuple[str, int]]) -> int:
        """尝试将 token 解析为技能目录相对路径。

        SKILL.md 中的 CLI 示例通常使用技能目录相对路径（如 scripts/xxx.py），
        而非项目根目录相对路径。此方法检查 token 是否存在于任何允许的技能目录中。

        Args:
            token: 原始路径 token（已剥离引号和尾部标点）
            zones: 当前 zone 列表

        Returns:
            匹配到的权限级别，或 NONE
        """
        for skill_name in self._skill_names:
            skill_prefix = f"extensions/skills/{skill_name}"
            candidate = os.path.normpath(os.path.join(skill_prefix, token))

            # 检查候选路径是否匹配技能 zone
            level = self._match_zone(candidate, zones)
            if level != NONE:
                # 验证文件实际存在（防止路径穿越到不存在的目录）
                abs_path = os.path.join(self.project_root, candidate)
                if os.path.exists(abs_path):
                    return level

        return NONE

    def _looks_like_write(self, command: str, path_token: str) -> bool:
        """启发式判断命令是否对路径执行写操作。"""
        write_indicators = [
            f"rm {path_token}", f"rm -rf {path_token}", f"rm -f {path_token}",
            f"mv ", f"cp ",
            f"> {path_token}", f">> {path_token}",
            f"tee {path_token}",
            f"sed -i", f"sed --in-place",
        ]
        cmd_lower = command.lower()
        return any(ind in cmd_lower for ind in write_indicators)

    @classmethod
    def for_agent(cls, project_root: str, skills: list[str]) -> AccessPolicy:
        return cls(project_root, skill_names=list(skills))

    @classmethod
    def unrestricted(cls) -> AccessPolicy:
        """不限制（向后兼容，用于未设置 policy 的场景）。"""
        policy = cls("", skill_names=[])
        policy._unrestricted = True
        return policy
