from abc import ABC, abstractmethod
from pathlib import Path


class BaseSkill(ABC):
    """Skill 基类：所有 Skill 必须实现 body、skill_dir、schema、run 四个成员"""
    name: str
    description: str
    tools: list[str] = []  # Skill 依赖的外部工具名

    @property
    @abstractmethod
    def body(self) -> str:
        """Skill 的 Markdown 正文，会注入到 system prompt 中"""
        ...

    @property
    @abstractmethod
    def skill_dir(self) -> Path:
        """Skill 所在目录，用于执行入口脚本时定位"""
        ...

    @property
    @abstractmethod
    def schema(self) -> dict:
        """Anthropic tool schema 格式，让 LLM 知晓此 Skill 的调用方式"""
        ...

    @abstractmethod
    async def run(self, **kwargs) -> str:
        """执行 Skill 逻辑，返回字符串结果"""
        ...
