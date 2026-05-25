---
name: a-share-stock-market
description: A股股票行情与基本信息查询工具。提供股票基本信息、历史行情、实时行情、市场指数等查询。触发词：股票行情、股价、K线、大盘指数、股票信息、实时行情 等。
---

# A股股票行情与基本信息查询

提供A股股票行情和基本信息查询能力，基于 AKShare 数据源，覆盖沪深两市全部上市公司。

## 工具列表

| action | 说明 | 典型输出 |
|--------|------|----------|
| `get_stock_info` | 股票基本信息 | 股票名称、行业、市值、流通股本、上市日期等 |
| `get_stock_price` | 历史行情 | 日K线数据（开盘价、最高价、最低价、收盘价、成交量） |
| `get_stock_realtime` | 实时行情 | 当前价格、涨跌幅、成交量、成交额、换手率 |
| `get_market_index` | 市场指数 | 指数历史行情数据（开盘/最高/最低/收盘/成交量） |

## 输入参数

- **action** (必需)：操作类型，可选值见上表
- **symbol** (必需)：股票代码，如 `600519`（茅台）、`000001`（平安银行）；指数代码：`000001`（上证指数）、`399001`（深证成指）、`399006`（创业板指）
- **period** (可选)：行情周期，默认 `daily`，可选值：`daily` / `weekly` / `monthly`
- **count** (可选)：返回数据条数，默认 30 条

## CLI 调用模板

所有命令的 working directory 为 `SKILL.md` 所在目录。

```bash
python3 scripts/run.py --action get_stock_info --symbol 600519
```

带可选参数的调用：

```bash
python3 scripts/run.py --action get_stock_price --symbol 600519 --period daily --count 30
```

## 执行流程

1. 从用户输入识别 action 和 symbol
2. 根据 action 选择对应的数据工具
3. 构造 CLI 命令并执行
4. 脚本通过 AKShare API 获取数据并返回 JSON 结果
5. 将数据结果呈现给用户

## 使用示例

| 场景 | 命令参数 |
|------|----------|
| 查询茅台基本信息 | `--action get_stock_info --symbol 600519` |
| 查询茅台近30日K线 | `--action get_stock_price --symbol 600519 --count 30` |
| 查询平安银行周K线 | `--action get_stock_price --symbol 000001 --period weekly` |
| 查询上证指数 | `--action get_market_index --symbol 000001` |

## 注意事项

- 股票代码为纯数字，不含交易所前缀（SH/SZ）
- `get_stock_realtime` 和 `get_market_index` 实时数据接口可能因网络环境不可达而失败
- 历史行情默认返回最近 30 个交易日数据，如需更多请指定 `--count` 参数
- 数据来源为 AKShare 免费接口，非即时数据，有 1-2 分钟延迟

## 配合其他 Skill 使用

本 skill 通常与 `a-share-financial-data` 配合使用，前者获取行情数据，后者获取财报数据，共同支撑完整的股票分析场景。
