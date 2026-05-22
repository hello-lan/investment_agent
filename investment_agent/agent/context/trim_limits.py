"""工具结果分级截断限制 — 按工具类型配置 _trim_context() 中的截断长度。"""

# 默认分级限制（字符数），按工具类别分组
DEFAULT_TRIM_LIMITS: dict[str, int] = {
    # 财报数据类 — 需要保留较多内容供后续分析引用
    "get_income_statement": 6000,
    "get_balance_sheet": 6000,
    "get_cash_flow": 5000,
    "get_valuation": 4000,
    "get_financial_indicators": 4000,
    # 市场数据类
    "get_stock_info": 2000,
    "get_stock_price": 3000,
    # Skill 结果 — 子skill输出需要保留
    "Skill": 4000,
    # 脚本执行 — 输出噪声大，激进截断
    "run_command": 1000,
}

# 未在表中列出的工具使用的兜底限制
DEFAULT_FALLBACK_LIMIT = 2000

# 绝对最低限制
MIN_TRIM_LIMIT = 200


def resolve_limit(tool_name: str | None, overrides: dict | None = None,
                  tool_trim_max_chars: int | None = None) -> int:
    """解析某工具在 _trim_context 中的截断字符限制。

    优先级: overrides > tool.trim_max_chars > DEFAULT_TRIM_LIMITS > fallback
    """
    if overrides and tool_name and tool_name in overrides:
        return max(MIN_TRIM_LIMIT, int(overrides[tool_name]))
    if tool_trim_max_chars is not None:
        return max(MIN_TRIM_LIMIT, tool_trim_max_chars)
    if tool_name and tool_name in DEFAULT_TRIM_LIMITS:
        return DEFAULT_TRIM_LIMITS[tool_name]
    return DEFAULT_FALLBACK_LIMIT
