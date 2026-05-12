from abc import ABC, abstractmethod


class BaseTool(ABC):
    """工具基类：所有工具必须实现 name、description、schema、run 四个成员"""
    name: str
    description: str
    risk_level: int = 0  # 风险等级 L0-L4，L0 只读，L2 可执行命令

    @property
    @abstractmethod
    def schema(self) -> dict:
        """返回 Anthropic tool schema 格式，供 LLM 理解工具用途"""
        ...

    @abstractmethod
    async def run(self, **kwargs) -> str:
        """执行工具逻辑，返回字符串结果"""
        ...
