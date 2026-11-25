---
name: a-share-financial-data
description: A股上市公司财务数据查询工具。提供利润表、资产负债表、现金流量表、估值指标、财务指标、历史分红、股票回购、公司动态等查询。触发词：财报、利润表、资产负债表、现金流、估值、PE、PB、ROE、财务指标、分红、回购、公司动态、公司公告 等。
---

# A股财务数据查询

提供A股上市公司财务数据的查询能力，基于 AKShare 数据源，覆盖沪深两市全部上市公司的财务报表、估值指标与公司事件类数据。

## 工具列表

| action | 说明 | 典型输出 |
|--------|------|----------|
| `get_income_statement` | 利润表 | 营业收入、营业成本、净利润、毛利率、净利率等 |
| `get_balance_sheet` | 资产负债表 | 总资产、总负债、股东权益、流动资产、流动负债等 |
| `get_cash_flow` | 现金流量表 | 经营活动现金流、投资活动现金流、筹资活动现金流 |
| `get_valuation` | 估值指标 | 市盈率(PE)、市净率(PB)、市销率(PS)、股息率、总市值 |
| `get_financial_indicators` | 财务指标 | ROE、ROA、毛利率、净利率、资产负债率、流动比率等 |
| `get_dividend_history` | 历史分红 | 送转比例、现金分红、股息率、股权登记日、除权除息日、方案进度 |
| `get_share_repurchase` | 股票回购 | 计划回购价格/数量/金额、实施进度、已回购数量与金额、公告日期 |
| `get_company_dynamics` | 公司动态 | 近一年个股公告标题、类型、日期与链接 |

## 输入参数

- **action** (必需)：操作类型，可选值见上表
- **symbol** (必需)：股票代码，如 `600519`（茅台）、`000001`（平安银行）

## CLI 调用模板

所有命令的 working directory 为 `SKILL.md` 所在目录。

```bash
python3 scripts/run.py --action get_income_statement --symbol 600519
```

```bash
python3 scripts/run.py --action get_valuation --symbol 000001
```

```bash
python3 scripts/run.py --action get_dividend_history --symbol 600519
```

```bash
python3 scripts/run.py --action get_share_repurchase --symbol 600519
```

```bash
python3 scripts/run.py --action get_company_dynamics --symbol 600519
```

## 执行流程

1. 从用户输入识别 action 和 symbol
2. 根据 action 选择对应的财务数据工具
3. 构造 CLI 命令并执行
4. 脚本通过 AKShare API 获取数据并返回结果
5. 将财务数据呈现给用户

## 使用示例

| 场景 | 命令参数 |
|------|----------|
| 查询茅台利润表 | `--action get_income_statement --symbol 600519` |
| 查询平安银行资产负债表 | `--action get_balance_sheet --symbol 000001` |
| 查询比亚迪估值 | `--action get_valuation --symbol 002594` |
| 查询茅台财务指标 | `--action get_financial_indicators --symbol 600519` |
| 查询格力电器现金流 | `--action get_cash_flow --symbol 000651` |
| 查询茅台历史分红 | `--action get_dividend_history --symbol 600519` |
| 查询茅台股票回购 | `--action get_share_repurchase --symbol 600519` |
| 查询茅台公司动态 | `--action get_company_dynamics --symbol 600519` |

## 注意事项

- 股票代码为纯数字，不含交易所前缀（SH/SZ）
- 财务数据按报告期返回，通常包含最近多个季度的数据
- 估值指标基于最新交易日数据计算，非实时更新
- `get_share_repurchase` 底层为全市场回购接口，首次拉取较慢，脚本会本地缓存约 24 小时
- `get_company_dynamics` 返回近一年个股公告（最多 30 条）
- 数据来源为 AKShare 免费接口，数据质量与及时性以 AKShare 为准

## 配合其他 Skill 使用

本 skill 通常与 `a-share-stock-market` 配合使用，前者获取财报与公司事件数据，后者获取行情数据，共同支撑完整的股票分析场景。
