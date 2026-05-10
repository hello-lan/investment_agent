from abc import ABC, abstractmethod


class BaseTool(ABC):
    name: str
    description: str
    risk_level: int = 0  # L0-L4

    @property
    @abstractmethod
    def schema(self) -> dict:
        """Anthropic tool schema format."""
        ...

    @abstractmethod
    async def run(self, **kwargs) -> str: ...
