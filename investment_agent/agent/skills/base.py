from abc import ABC, abstractmethod
from pathlib import Path


class BaseSkill(ABC):
    name: str
    description: str
    tools: list[str] = []

    @property
    @abstractmethod
    def body(self) -> str:
        ...

    @property
    @abstractmethod
    def skill_dir(self) -> Path:
        ...

    @property
    @abstractmethod
    def schema(self) -> dict:
        ...

    @abstractmethod
    async def run(self, **kwargs) -> str:
        ...
