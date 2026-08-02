"""ReAct + Subagent 执行引擎。"""

from .react_loop import ReactLoopEngine


class ReactSubagentLoopEngine(ReactLoopEngine):
    """与标准 ReAct 共享主循环，但额外暴露 Subagent 能力。"""
