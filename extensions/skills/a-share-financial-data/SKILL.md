---
name: a-share-financial-data
description: A股上市公司行情与财务数据查询工具。提供股票基本信息、历史/实时行情、市场指数、利润表、资产负债表、现金流量表、估值指标、财务指标、历史分红、股票回购、公司动态等查询。触发词：股票行情、股价、K线、大盘指数、股票信息、实时行情、财报、利润表、资产负债表、现金流、估值、PE、PB、ROE、财务指标、分红、回购、公司动态 等。
---

# A股行情与财务数据查询

提供A股上市公司行情与财务数据的查询能力，基于 AKShare 数据源，覆盖沪深两市全部上市公司的行情、财务报表、估值指标与公司事件类数据。

## 工具列表

### 行情与基本信息

| action | 说明 | 典型输出 |
|--------|------|----------|
| `get_stock_info` | 股票基本信息 | 股票名称、行业、市值、流通股本、上市日期等 |
| `get_stock_price` | 历史行情 | 日K线数据（开盘价、最高价、最低价、收盘价、成交量） |
| `get_stock_realtime` | 实时行情 | 当前价格、涨跌幅、成交量、成交额、换手率 |
| `get_market_index` | 市场指数 | 指数历史行情数据（开盘/最高/最低/收盘/成交量） |

### 财务报表与估值

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
- **symbol** (必需)：股票代码，如 `600519`（茅台）、`000001`（平安银行）；指数代码：`000001`（上证指数）、`399001`（深证成指）、`399006`（创业板指）
- **period** (可选)：行情周期，默认 `daily`，可选值：`daily` / `weekly` / `monthly`（仅 `get_stock_price`）
- **count** (可选)：返回数据条数，默认 30 条（仅行情/指数类 action）

## CLI 调用模板

所有命令的 working directory 为 `SKILL.md` 所在目录。

```bash
python3 scripts/run.py --action get_stock_info --symbol 600519
```

```bash
python3 scripts/run.py --action get_stock_price --symbol 600519 --period daily --count 30
```

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
2. 根据 action 选择对应的数据工具
3. 构造 CLI 命令并执行
4. 脚本通过 AKShare API 获取数据并返回结果
5. 将数据结果呈现给用户

## 使用示例

| 场景 | 命令参数 |
|------|----------|
| 查询茅台基本信息 | `--action get_stock_info --symbol 600519` |
| 查询茅台近30日K线 | `--action get_stock_price --symbol 600519 --count 30` |
| 查询平安银行周K线 | `--action get_stock_price --symbol 000001 --period weekly` |
| 查询上证指数 | `--action get_market_index --symbol 000001` |
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
- `get_stock_realtime` 和 `get_market_index` 实时数据接口可能因网络环境不可达而失败
- 历史行情默认返回最近 30 个交易日数据，如需更多请指定 `--count` 参数
- 财务数据按报告期返回，通常包含最近多个季度的数据
- 估值指标基于最新交易日数据计算，非实时更新
- `get_share_repurchase` 底层为全市场回购接口，首次拉取较慢，脚本会本地缓存约 24 小时
- `get_company_dynamics` 返回近一年个股公告（最多 30 条）
- 数据来源为 AKShare 免费接口，数据质量与及时性以 AKShare 为准，行情有 1-2 分钟延迟
