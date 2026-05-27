#!/bin/bash
# 从年报附注文件中提取排雷分析所需的关键数据段
# 用法: bash extract_notes.sh <附注文件路径> <输出文件路径>

set -e
NOTES="$1"
OUT="$2"

if [ ! -f "$NOTES" ]; then
    echo "ERROR: 附注文件不存在: $NOTES"
    exit 1
fi

echo "## 附注关键数据" >> "$OUT"
echo "" >> "$OUT"

# 一次 grep 定位所有关键段落的行号
LINES=$(grep -n "^[0-9]*、 货币资金$\|^[0-9]*、 应收票据$\|^[0-9]*、 应收账款$\|^[0-9]*、 预付款项$\|^[0-9]*、 存货$\|^[0-9]*、 固定资产$\|^[0-9]*、 在建工程$\|^[0-9]*、 商誉$\|^[0-9]*、 短期借款$\|^[0-9]*、 长期借款$\|关联交易情况\|所有权或使用权受到限制" "$NOTES" | head -50)

echo "关键段落定位：" >> "$OUT"
echo '```' >> "$OUT"
echo "$LINES" >> "$OUT"
echo '```' >> "$OUT"
echo "" >> "$OUT"

# 提取各段（宽范围，一次覆盖多个数据点）
extract_section() {
    local start=$1
    local end=$((start + 60))
    echo "--- 行${start}-${end} ---" >> "$OUT"
    sed -n "${start},${end}p" "$NOTES" >> "$OUT"
    echo "" >> "$OUT"
}

# 货币资金（行号由 grep 结果确定）
CASH_LINE=$(echo "$LINES" | grep "货币资金" | head -1 | cut -d: -f1)
if [ -n "$CASH_LINE" ]; then
    extract_section "$((CASH_LINE - 2))"
fi

# 应收票据 + 应收账款（通常相邻）
AR_LINE=$(echo "$LINES" | grep "应收票据" | head -1 | cut -d: -f1)
if [ -n "$AR_LINE" ]; then
    # 从应收票据前5行读到应收账款后80行，覆盖账龄和坏账
    sed -n "$((AR_LINE - 5)),$((AR_LINE + 120))p" "$NOTES" >> "$OUT"
    echo "" >> "$OUT"
fi

# 存货
INV_LINE=$(echo "$LINES" | grep "、 存货$" | head -1 | cut -d: -f1)
if [ -n "$INV_LINE" ]; then
    extract_section "$((INV_LINE - 2))"
fi

# 固定资产 + 在建工程
FA_LINE=$(echo "$LINES" | grep "固定资产" | head -1 | cut -d: -f1)
if [ -n "$FA_LINE" ]; then
    sed -n "$((FA_LINE - 5)),$((FA_LINE + 90))p" "$NOTES" >> "$OUT"
    echo "" >> "$OUT"
fi

# 短期借款 + 长期借款 + 关联交易（后半段）
ST_LOAN=$(echo "$LINES" | grep "短期借款" | head -1 | cut -d: -f1)
if [ -n "$ST_LOAN" ]; then
    sed -n "$((ST_LOAN - 3)),$((ST_LOAN + 80))p" "$NOTES" >> "$OUT"
    echo "" >> "$OUT"
fi

echo "extract_notes done: $(wc -l < "$OUT") lines in output" >&2
