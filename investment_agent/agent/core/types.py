"""Provider 共享数据类型 — 独立模块以避免循环导入。

ToolCall 和 LLMResponse 被 provider / response_parser / message_converter 等模块共用，
提取到此文件避免 provider.py 与 response_parser.py 之间的循环依赖。
"""

from dataclasses import dataclass, field

from ..constants import StopReason


@dataclass
class ToolCall:
    """LLM 返回的单个工具调用"""
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    """统一的 LLM 响应格式，屏蔽不同 Provider 的差异"""
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    extra_blocks: list[dict] = field(default_factory=list)  # Anthropic 专有 content blocks
    reasoning_content: str | None = None  # 深度求索等模型的思考内容
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = StopReason.END_TURN
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
