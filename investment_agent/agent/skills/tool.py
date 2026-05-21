"""Skill 加载工具：LLM 按需加载 Skill 的完整 body。"""

from ..tools.base import BaseTool
from .loader import _registry
from .cache import get_cache


class SkillTool(BaseTool):
    """按需加载 Skill body。调用时传入 skill 名称，返回该 skill 的完整使用说明。"""
    name = "Skill"
    description = (
        "加载指定技能的完整使用说明。当你需要执行某个技能时，先用此工具获取该技能的详细指令、"
        "参数说明和操作步骤，然后再按指令执行。"
    )
    risk_level = 0

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要加载的技能名称，如 download-a-share-reports",
                    },
                },
                "required": ["name"],
            },
        }

    async def run(self, name: str) -> str:
        skill = _registry.get(name)
        if skill is None:
            available = ", ".join(sorted(_registry.keys())) or "(无)"
            return f"技能 '{name}' 不存在。当前可用技能: {available}"

        cache = get_cache()
        body = cache.get(name, skill.main_md_path, skill.skill_dir)
        return body
