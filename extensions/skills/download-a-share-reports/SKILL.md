---
name: download-a-share-reports
description: 从巨潮资讯网、东方财富、新浪财经等多数据源下载 A 股上市公司财务报告。当用户要求下载中国股票的年度报告、季度报告、半年度报告或财务报告时，应使用此技能。触发词包括"下载财报"、"下载年报"、"下载季报"、"下载半年报"、"download financial reports"、"下载XXX的年报"等。支持自然语言股票名称（如茅台、宁德时代）和股票代码。
---

# A股财报下载（多数据源）

通过巨潮资讯网、东方财富、新浪财经等多数据源下载上市公司定期报告 PDF 文件。**某个数据源失败时自动切换下一数据源**，解决网络不稳定和反爬机制导致的下载失败问题。

## 数据源

| 优先级 | 数据源 | 类型 | 说明 |
|--------|--------|------|------|
| 1 | 巨潮资讯网 (cninfo) | API | 证监会指定信息披露平台，覆盖最全 |
| 2 | 东方财富 (eastmoney) | API | 主流金融数据平台，稳定性好 |
| 3 | 新浪财经 (sina) | 网页 | 综合财经门户，作为补充备用 |

下载时按优先级自动尝试，成功即停止；全部失败则提示用户。

## 脚本位置

| 脚本 | 说明 |
|------|------|
| `scripts/download_report.py` | **主入口**，多数据源编排器（推荐使用） |
| `scripts/sources/cninfo_spider.py` | 巨潮资讯网爬虫（可独立运行） |
| `scripts/sources/eastmoney_spider.py` | 东方财富爬虫（可独立运行） |
| `scripts/sources/sina_spider.py` | 新浪财经爬虫（可独立运行） |

## 触发规则

以下情况应使用本 skill：

| 用户说 | 触发？ |
|--------|--------|
| "下载贵州茅台2020-2024年的年报" | ✅ |
| "下载600519的年报" | ✅ |
| "批量下载茅台和五粮液的财报" | ✅ |
| "帮我下一下宁德时代的季报" | ✅ |
| "get annual reports for Moutai" | ✅ |
| "下载腾讯的财报" | ⚠️ 腾讯是港股，巨潮资讯网主要覆盖A股 |

## 参数提取规则

从用户自然语言中提取参数：

| 用户表述 | 参数 | 示例值 |
|----------|------|--------|
| "2020-2024年" / "近五年" / "最近3年" | `--start` `--end` | `--start 2020 --end 2024` |
| "年报" / "年度报告" | `--category 年报` | 默认值 |
| "半年报" / "中报" | `--category 半年报` | |
| "季报" / "一季报" / "三季报" | `--category 季报` | |
| 未指定年份范围 | `--start` `--end` | 默认最近 5 年 |
| 未指定报告类型 | `--category` | 默认年报 |

## CLI 调用模板

所有命令的 working directory 为 `SKILL.md` 所在目录：

```bash
# ⚠️ --save-dir 为必填项，指向项目 data/reports/pdf/ 目录
SAVE_DIR="/Users/macbookair/project/investment_agent/data/reports/pdf"

# 单个股票（代码）— 多数据源自动切换
cd scripts && python download_report.py --stock 600519 --start 2020 --end 2024 --category 年报 --save-dir "$SAVE_DIR"

# 单个股票（名称）
cd scripts && python download_report.py --name 茅台 --start 2020 --end 2024 --save-dir "$SAVE_DIR"

# 批量下载
cd scripts && python download_report.py --names 茅台,五粮液,宁德时代 --start 2020 --end 2024 --category 年报 --save-dir "$SAVE_DIR"

# 强制使用指定数据源
cd scripts && python download_report.py --name 茅台 --source eastmoney --save-dir "$SAVE_DIR"

# 独立运行某个数据源（同样需要 --save-dir）
cd scripts && python sources/cninfo_spider.py --stock 600519 --start 2020 --end 2024 --save-dir "$SAVE_DIR"
cd scripts && python sources/eastmoney_spider.py --stock 600519 --start 2020 --end 2024 --save-dir "$SAVE_DIR"
cd scripts && python sources/sina_spider.py --stock 600519 --start 2020 --end 2024 --save-dir "$SAVE_DIR"
```

## 常见股票代码速查

| 名称 | 代码 | 行业 |
|------|------|------|
| 贵州茅台 | 600519 | 白酒 |
| 五粮液 | 000858 | 白酒 |
| 宁德时代 | 300750 | 新能源 |
| 比亚迪 | 002594 | 新能源/汽车 |
| 招商银行 | 600036 | 银行 |
| 中国平安 | 601318 | 保险 |
| 恒瑞医药 | 600276 | 医药 |
| 海康威视 | 002415 | 科技 |
| 美的集团 | 000333 | 家电 |
| 格力电器 | 000651 | 家电 |
| 隆基绿能 | 601012 | 光伏 |
| 万科A | 000002 | 地产 |

完整映射表见 `scripts/download_report.py` 中的 `STOCK_NAME_MAP`。

## 执行流程

1. 从用户输入提取：股票名称/代码、年份范围、报告类型、结果保存目录
2. 如果用户使用股票名称，先查速查表确认代码；如果是未知名称，仍传入 CLI 尝试模糊匹配
3. 构造 CLI 命令并执行（working directory = SKILL.md 所在目录）
4. **多数据源自动切换**：按优先级尝试 cninfo → eastmoney → sina，成功即停止
5. 将下载进度、使用的数据源和结果汇报给用户
6. 如果全部数据源均失败，提示用户检查网络或稍后重试

## 输出位置

**在 investment_agent 项目中，必须通过 `--save-dir` 指定保存路径**，与项目文件输出规范保持一致：

PDF 文件将保存到 `{save_dir}/{stock_code}/` 目录下（如 `data/reports/pdf/600519/`）。

## 限制说明

- 仅支持 A 股（沪深北交易所），不支持港股/美股
- 需要网络访问对应数据源
- 大量下载建议每次不超过 10 只股票
- 默认请求间隔 0.5 秒，可通过 `--delay` 调整
- 新浪财经数据源基于网页解析，稳定性低于 API 类数据源
