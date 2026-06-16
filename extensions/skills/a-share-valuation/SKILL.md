---
name: a-share-valuation
description: A股估值分析工具。基于自由现金流折现（DCF）、相对估值（PE/PB/PS）和周期股调整估值，输出前提显式的估值观察区间。触发词：估值、DCF、PE、PB、合理价位、内在价值、周期股估值。不提供买卖建议。
---

# A股估值分析

基于《手把手教你读财报》估值方法论，在排雷通过后进行**前提显式**的估值推演。

## 工具列表

| action | 说明 |
|--------|------|
| `full_valuation` | 综合估值：DCF 三情景 + 相对估值 + 周期股调整（如适用） |
| `dcf` | 自由现金流折现（乐观/中性/悲观三情景） |
| `relative` | 相对估值：PE/PB/PS 与行业对比 |
| `cycle_adjusted` | 周期股：10 年平均利润 × 合理 PE |

## 输入参数

- **action** (必需)：见上表
- **symbol** (必需)：6 位股票代码，如 `600519`
- **discount_rate** (可选)：折现率，默认 0.10
- **terminal_growth** (可选)：永续增长率，默认 0.025
- **growth_years** (可选)：显性预测期年数，默认 5

## CLI 调用

```bash
python3 extensions/skills/a-share-valuation/scripts/run.py --action full_valuation --symbol 600519
```

```bash
python3 extensions/skills/a-share-valuation/scripts/run.py --action dcf --symbol 600519 --discount-rate 0.09
```

## 输出说明

脚本输出 JSON，包含：
- `premises`：估值三大前提判断（利润为真/可持续/低资本投入）
- `dcf`：三情景每股内在价值区间
- `relative`：当前 PE/PB 与行业均值对比
- `cycle_adjusted`：周期股调整后 PE（如检测到周期特征）
- `summary`：文字摘要（非交易指令）

## 注意事项

- 估值前应先完成财报排雷，利润存疑时置信度自动下调
- DCF 对假设敏感，务必关注三情景区间而非单点
- 周期股禁止使用景气高点利润 × PE
- 本工具输出研究框架下的估值观察，不构成投资建议
