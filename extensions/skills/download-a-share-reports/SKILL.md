---
name: download-a-share-reports
description: 从巨潮资讯网、东方财富、新浪财经等多数据源下载 A 股上市公司财务报告。当用户要求下载中国股票的年度报告、季度报告、半年度报告或财务报告时，应使用此技能。触发词包括"下载财报"、"下载年报"、"下载季报"、"下载半年报"、"download financial reports"、"下载XXX的年报"等。支持自然语言股票名称（如茅台、宁德时代）和股票代码。
---

# A股财报下载（多数据源）

```text
base_dir = data/reports/pdf
```

- 上面这一行是默认值。执行前先看 agent 系统提示词里有没有另外给出 `base_dir = ...`。有则以系统提示词为准，没有才用默认值。
- 后文的 `{base_dir}` 都指解析后的那一个值。路径相对项目根，用 `/`。PDF 写到 `{base_dir}/<code>/`。
- 调用脚本时把解析后的值传给 `save_dir` / `--save-dir`，不要省略。这样系统提示词里的目录会盖过脚本自带的 `data/reports/pdf`。
- 完整 PDF 只认 `{base_dir}/<code>/`。`data/reports/<code>/1_pdf/` 以及其它目录里的文件忽略，不读取、不搬迁。

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

## 调用模板

**优先 `run_python_script`**（cwd=项目根）。**不要 `cd` 进 `scripts/`**；相对 `--save-dir` 按项目根解析，取值用解析后的 `{base_dir}`。仅当专用工具不可用时再用 `run_command`。

```text
run_python_script(
  script_path="extensions/skills/download-a-share-reports/scripts/download_report.py",
  kwargs={"stock": "600519", "start": 2020, "end": 2024, "category": "年报", "save_dir": "{base_dir}"},
  timeout_seconds=120
)
```

其它常用 kwargs：`name` / `names` / `source`（如 `eastmoney`）。也可把旗标拆进 `argv`。

`run_command` 兜底示例：

```bash
python extensions/skills/download-a-share-reports/scripts/download_report.py \
  --stock 600519 --start 2020 --end 2024 --category 年报 --save-dir {base_dir}
```

下载成功后直接使用脚本打印的路径，**不要再 `find` / 全量 `list_files` 探路**。

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
3. 用 `run_python_script` 执行（见上方模板）；必要时才用 `run_command`
4. **多数据源自动切换**：按优先级尝试 cninfo → eastmoney → sina，成功即停止
5. 将下载进度、使用的数据源和**输出路径**汇报给用户
6. 如果全部数据源均失败，提示用户检查网络或稍后重试

## 输出位置

PDF 保存到 `{base_dir}/{stock_code}/`（如 `{base_dir}/600519/`）。只有这个目录下的文件算已下载；约定外路径里的同名 PDF 忽略。

## 限制说明

- 仅支持 A 股（沪深北交易所），不支持港股/美股
- 需要网络访问对应数据源
- 大量下载建议每次不超过 10 只股票
- 默认请求间隔 0.5 秒，可通过 `--delay` 调整
- 新浪财经数据源基于网页解析，稳定性低于 API 类数据源
