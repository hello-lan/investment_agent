from .base import BaseSkill
from .markdown_parser import ParsedSkill
from .script_runner import run_skill_entry


class MarkdownSkill(BaseSkill):
    def __init__(self, parsed: ParsedSkill):
        self.name = parsed.name
        self.description = parsed.description
        self.tools = parsed.tools
        self._schema = parsed.schema
        self._entry = parsed.entry
        self._skill_dir = parsed.skill_dir

    @property
    def schema(self) -> dict:
        return self._schema

    async def run(self, **kwargs) -> str:
        return run_skill_entry(self._skill_dir, self._entry, kwargs)
