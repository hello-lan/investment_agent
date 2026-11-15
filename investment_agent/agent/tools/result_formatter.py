"""安全文件工具结果格式化辅助。"""

from __future__ import annotations


_RESULT_HEADER_PREFIX = "[result]"


def _format_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def format_tool_result(tool_name: str, body: str, **metadata) -> str:
    """输出带元信息头的工具结果文本。"""
    lines = [_RESULT_HEADER_PREFIX, f"tool={tool_name}"]
    for key, value in metadata.items():
        if value is None:
            continue
        lines.append(f"{key}={_format_value(value)}")
    header = "\n".join(lines)
    return header if not body else f"{header}\n\n{body}"
