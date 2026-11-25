"""引擎提示词。调用方只从本包导入共用系统提示，工具说明留在工具文件。"""

from .auxiliary import TITLE_SYSTEM_PROMPT, TITLE_USER_PREFIX
from .engine import (
    DATE_NOTE,
    DATE_NOTE_RE,
    PROGRESS_EVAL,
    SLOW_THINK_PROMPT,
    STEP_BUDGET_MARKER,
    STEP_BUDGET_WARNING,
    TRUNCATION_CONTINUE_PROMPT,
    slow_think_reflection,
)
from .system import (
    DEFAULT_SYSTEM_PROMPT,
    MOUNTED_MARKER,
    OFFLOAD_AWARE_PROMPT,
    OFFLOAD_NO_SHELL,
    PROJECT_PATH_MARKER,
    ROUTING_MARKER,
    SKILLS_MARKER,
    defined_subagent_preamble,
    mounted_section,
    project_path_section,
    routing_section,
    skill_quick_reference,
    skills_section,
)

__all__ = [
    "DATE_NOTE",
    "DATE_NOTE_RE",
    "DEFAULT_SYSTEM_PROMPT",
    "MOUNTED_MARKER",
    "OFFLOAD_AWARE_PROMPT",
    "OFFLOAD_NO_SHELL",
    "PROGRESS_EVAL",
    "PROJECT_PATH_MARKER",
    "ROUTING_MARKER",
    "SKILLS_MARKER",
    "SLOW_THINK_PROMPT",
    "STEP_BUDGET_MARKER",
    "STEP_BUDGET_WARNING",
    "TITLE_SYSTEM_PROMPT",
    "TITLE_USER_PREFIX",
    "TRUNCATION_CONTINUE_PROMPT",
    "defined_subagent_preamble",
    "mounted_section",
    "project_path_section",
    "routing_section",
    "skill_quick_reference",
    "skills_section",
    "slow_think_reflection",
]
