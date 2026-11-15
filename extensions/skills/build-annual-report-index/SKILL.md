---
name: build-annual-report-index
description: 为 A 股年报 Markdown 生成最多两级的 chapter 索引 JSON；先增量读取目录，再逐段定位正文标题，适合新年报接入、补建索引和低上下文章节导航。
---

# Build Annual Report Index

这个 skill 只负责一件事：
**给一份上市公司年报 Markdown 生成一个最多两级的 chapter 索引 JSON。**

它不负责：
- 默认生成 digest
- 默认输出公司分析结论
- 默认通读整份年报

## Core objective

你要创建的是**低上下文、可复用、可验证**的章节索引，而不是把年报全文切碎后全部读进上下文。

第一目标是让后续流程能够：
1. 先按目录理解全书结构
2. 再按 `line_start + line_end` 精准回查
3. 尽量使用报告里的真实标题，而不是强行套固定章节名

## Inputs

至少确认：
- `report_path`
  - 例如：`reports/company-a/annual-report-2024.md`

可选输入：
- `output_path`
  - 若上游 workflow 已指定索引输出位置，应优先写到该路径

## Outputs

至少产出：
1. 一个 chapter 索引 JSON
2. 一段简短执行摘要，说明：
   - 命中了哪些顶层章节
   - 哪些章节带有二级 children
   - 财务报告中命中了哪些关键条目
   - 哪些章节缺失或需要人工复核

默认示例输出位置：
- 与报告同级：`<report_dir>/<report_stem>.sections.json`

不同项目里也可能存在其他历史布局，但这些都只是历史示例；若调用方显式给出 `output_path`，优先写到指定位置。

## Canonical rule files

本 skill 自带所需规则与模板：
- `references/index-generation-rules.md`
- `references/section-priority-rules.md`
- `templates/section-index-template.json`
- `references/usage-examples.md`

这些文件定义了：
- 章节树输出结构
- 标题定位原则
- 财务报告特殊处理规则
- 优先级与 reason 写法

## Required workflow

### Step 1: 先增量读取目录，不先读全文
- 从文件开头开始读取
- 每次只读取 200 行
- 循环读取，直到可以确认目录已经完整出现
- 目录确认后立即停止继续向后大段读取

目标：
- 确认本年报的顶层章节顺序
- 确认公司实际使用的章节命名
- 为后续正文定位提供 strongest aliases

注意：
- 目录是“顺序来源”，不是正文行号来源
- 目录里命中的标题不能直接当作正文 `line_start`

### Step 2: 先建立顶层章节骨架
- 根据目录，把除最后一个 `财务报告` 外的所有顶层章节都纳入索引
- 名称优先使用目录中的实际标题
- 再搜索正文中对应的真实标题位置
- 用下一个已确认顶层章节的 `line_start - 1` 计算当前 `line_end`

### Step 3: 只对两个章节展开一层 children
只对以下顶层章节展开一层二级索引：
- `公司简介和主要财务指标`
- `管理层讨论与分析`

做法：
1. 先确定父章节边界
2. 仅在父章节范围内逐行扫描
3. 提取形如 `一、`、`二、`、`三、` 的一层小节标题
4. 对跨行、断裂标题，允许拼接少量窗口后再判断

不要：
- 依赖目录去找二级标题
- 默认重新读取整份年报
- 继续展开第三层

### Step 4: 对财务报告做特殊处理
最后一个 `财务报告` 不保留为父节点。

你应先定位 `财务报告` 在正文中的真实起点，然后仅把它当作一个搜索窗口，在其中提取以下关键条目，并提升到顶层：
- `财务报告-审计报告`
- `财务报告-合并资产负债表`
- `财务报告-合并现金流量表`
- `财务报告-合并利润表`
- `财务报告-重要会计政策及会计估计`
- `财务报告-合并报表附注`

注意：
- 命中时应尽量保留原文真实标题，再统一加 `财务报告-` 前缀
- 标题可以有同义写法、断裂、排版差异
- 只有 `财务报告-合并报表附注` 允许继续展开一层 children

### Step 5: 对合并报表附注建立一层 children
如果已经定位到 `财务报告-合并报表附注`：
- 仅在该区段内部继续扫描，不重新搜索整份年报
- 尽量建立一层附注科目 children，例如：
  - `1、货币资金`
  - `2、交易性金融资产`
  - `4、应收票据`
- 只建立一层主条目，不继续递归到 `（1）`、`（2）`
- 子项名称以原文实际命中标题为准，不预设固定科目名清单

### Step 6: 校验结构
生成后至少检查：
- 顶层节点是否按行号单调递增
- 是否错误保留了原始 `财务报告` 父节点
- `公司简介和主要财务指标`、`管理层讨论与分析` 是否存在一层 children
- `财务报告-合并报表附注` 是否存在一层 children
- 是否出现第三层结构
- 行号区间是否有效且不重叠

## Preferred implementation path

优先使用本 skill 自带脚本：
- `scripts/build_minimal_index.py`
- `scripts/validate_sections_index.py`

推荐命令：

```bash
python extensions/skills/build-annual-report-index/scripts/build_minimal_index.py \
  reports/company-a/annual-report-2024.md \
  --output reports/company-a/annual-report-2024.sections.json \
  --pretty
```

校验输出：

```bash
python extensions/skills/build-annual-report-index/scripts/validate_sections_index.py \
  reports/company-a/annual-report-2024.sections.json
```

## Output contract

输出 JSON 顶层至少包含：
- `report_file`
- `company`
- `ticker`
- `year`
- `index_version`
- `chapters`

每个 chapter 节点至少包含：
- `chapter_id`
- `title`
- `line_start`
- `line_end`
- `priority`
- `reason`
- 可选 `children`

## Guardrails

- 不要默认读取整份年报
- 不要把目录命中当成正文命中
- 不要继续输出旧的平面 `sections`
- 不要保留原始 `财务报告` 父节点
- 不要把附注展开到第三层
- 不要预设附注科目固定名称
- 若上游已指定 `output_path`，不要再擅自改写到其他固定目录
