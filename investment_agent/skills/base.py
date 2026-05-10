from abc import ABC, abstractmethod


class BaseSkill(ABC):
    name: str
    description: str
    tools: list[str] = []

    @property
    @abstractmethod
    def schema(self) -> dict:
        ...

    @abstractmethod
    async def run(self, **kwargs) -> str:
        ...
