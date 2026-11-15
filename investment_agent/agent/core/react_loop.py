"""标准 ReAct 单循环执行引擎。"""

from .base_loop import BaseLoopEngine


class ReactLoopEngine(BaseLoopEngine):
    """标准 ReAct 主循环：无慢思考支线。"""
