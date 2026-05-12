from pathlib import Path

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
        self._body = parsed.body

    @property
    def body(self) -> str:
        return self._body.strip()

    @property
    def skill_dir(self) -> Path:
        return self._skill_dir

    @property
    def schema(self) -> dict:
        return self._schema

    async def run(self, **kwargs) -> str:
        if self._entry:
            return run_skill_entry(self._skill_dir, self._entry, kwargs)
        return self._body.strip()
