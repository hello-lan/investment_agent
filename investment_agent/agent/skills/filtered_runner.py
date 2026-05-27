"""技能过滤运行器 — 供 runner.py 和 subagent.py 共用。

将技能名称过滤逻辑封装为工厂函数，避免在两处维护相同的闭包代码。
"""

from __future__ import annotations

from typing import Callable


def make_filtered_skill_runner(
    allowed_names: set[str],
    original_run: Callable,
) -> Callable:
    """创建带名称过滤的技能运行闭包。

    Args:
        allowed_names: 允许调用的技能名称集合
        original_run: SkillTool 的原始 run 方法

    Returns:
        过滤后的 run 函数，仅允许调用 allowed_names 中的技能
    """

    async def filtered_run(
        name, _orig=original_run, _allowed=allowed_names,
    ):
        if name not in _allowed:
            available = ", ".join(sorted(_allowed)) or "(无)"
            return (
                f"技能 '{name}' 不在当前Agent的启用列表中。"
                f"可用技能: {available}"
            )
        return await _orig(name=name)

    return filtered_run
