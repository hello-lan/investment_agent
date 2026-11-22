"""把本会话计划写到 data/plans/{session_id}.md。"""

from __future__ import annotations

import re
from pathlib import Path

from ...config import ROOT_DIR
from .base import BaseTool

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

PLAN_BLOCKED_TOOLS = frozenset({
    "write_file",
    "run_command",
    "run_python_script",
    "DelegateTask",
})

PLAN_MODE_PROMPT = (
    "\n\n## 规划模式\n"
    "你当前处于规划模式。本轮只能调研并提交计划，不能改数据文件、不能跑命令或脚本、不能委派。\n"
    "用户用命令式口吻要求立刻执行时，仍然只完善计划。命令式口吻不能结束规划。\n"
    "计划必须能直接交给下一轮执行，写清：目标、明确不做的事、要用的数据和技能、有序步骤、验收标准。"
    "执行轮不再重新做设计决定。\n"
    "调研完成后调用 propose_plan 提交计划，然后停止。\n"
)


def plan_relpath(session_id: str) -> str:
    """会话计划的相对路径。非法 session_id 直接拒绝，避免写出 data/plans 之外。"""
    if not _SESSION_ID_RE.match(session_id or ""):
        raise ValueError("invalid session id")
    return f"data/plans/{session_id}.md"


def plan_file_path(session_id: str) -> Path:
    """解析并校验计划文件的绝对路径。"""
    path = (ROOT_DIR / plan_relpath(session_id)).resolve()
    plans_dir = (ROOT_DIR / "data" / "plans").resolve()
    if path.parent != plans_dir:
        raise ValueError("invalid plan path")
    return path


def approve_plan_message(session_id: str) -> str:
    """批准后发给执行轮的固定用户消息。"""
    return f"已批准计划，请按 {plan_relpath(session_id)} 执行。先读取该文件，计划里没写的不要做。"


class ProposePlanTool(BaseTool):
    name = "propose_plan"
    description = (
        "提交本会话的执行计划并结束规划。"
        "plan 必须包含目标、不做的事、数据和技能、有序步骤、验收标准。"
        "调用后不要再调用其他工具。"
    )
    risk_level = 1

    def __init__(self, session_id: str):
        self.session_id = session_id

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "overview": {
                        "type": "string",
                        "description": "一两句话说明这份计划要完成什么",
                    },
                    "plan": {
                        "type": "string",
                        "description": "完整 Markdown 计划：目标、不做的事、数据和技能、有序步骤、验收标准",
                    },
                },
                "required": ["overview", "plan"],
            },
        }

    async def run(self, overview: str = "", plan: str = "") -> str:
        overview = str(overview or "").strip()
        body = str(plan or "").strip()
        if not overview or not body:
            return "错误: overview 和 plan 都不能为空"
        try:
            path = plan_file_path(self.session_id)
            rel = plan_relpath(self.session_id)
        except ValueError as e:
            return f"错误: {e}"
        if not body.startswith("#"):
            body = f"# {overview}\n\n{body}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return f"已写入计划: {rel}"
