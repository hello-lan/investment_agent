---
name: industry-compare
description: A股同业对比分析工具。拉取目标公司与同行业可比公司的关键财务指标，标注异常偏离。触发词：行业对比、同业比较、对标、peer comparison、和同行比。
---

# A股同业对比

对目标公司与同行业可比公司进行关键指标横向对比，识别异常偏离。

## 工具列表

| action | 说明 |
|--------|------|
| `compare` | 与行业 peers 对比 ROE、毛利率、负债率、CFNP、增速等 |
| `list_peers` | 列出目标公司的行业可比公司列表 |

## 输入参数

- **action** (必需)：`compare` 或 `list_peers`
- **symbol** (必需)：6 位股票代码
- **peer_count** (可选)：对比公司数量，默认 5

## CLI 调用

```bash
python3 extensions/skills/industry-compare/scripts/run.py --action compare --symbol 600519
```

```bash
python3 extensions/skills/industry-compare/scripts/run.py --action list_peers --symbol 000001 --peer-count 8
```

## 输出说明

JSON 格式，包含：
- `target`：目标公司基本信息与指标
- `industry`：行业名称与行业均值（如有）
- `peers`：可比公司列表及关键指标
- `deviations`：相对行业/均值的异常偏离标注

## 数据来源

- 东财 `stock_zh_valuation_comparison_em`：行业 peers 与估值对比
- AKShare `stock_financial_analysis_indicator`：财务指标
