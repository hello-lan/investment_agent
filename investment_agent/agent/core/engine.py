"""兼容层：保留 AgentEngine 名称，默认指向双循环实现。"""

from .dual_loop import DualLoopEngine

# 向后兼容：历史引用仍可 import AgentEngine
AgentEngine = DualLoopEngine

__all__ = ["AgentEngine", "DualLoopEngine"]
