---
name: orch-full-financial-analysis
type: orch
description: 完整财报分析流程：下载A股近3年完整财报PDF → PDF转Markdown → 财报章节切割 → 财务排雷分析。当用户要求对某只A股进行完整财务分析时触发（如"分析茅台财报"、"对XXX做财务尽调"、"全面分析XXX的财务状况"）。
depends_on:
  - download-a-share-reports
  - pdf-to-markdown
  - split-financial-report
  - a-share-financial-forensic
---

# 完整财报分析流程（编排）

每个步骤必须委派给子Agent执行。串行执行以下 4 个步骤，每步完成后再进入下一步。任一步骤失败时停止并报告用户。

## 前置确认

执行前确认以下信息（用户未明确提供时主动询问）：
- **股票名称或代码**（必填）
- **报告年份范围**（默认：近 3 年完整年报）
- **报告类型**（默认：年报，非摘要）

---

## 步骤 1：下载财报 PDF

用 **download-a-share-reports** 技能下载指定股票的年度报告 PDF 文件，保存位置为 `data/reports/{股票代码}/1_pdf/`。

**输入**：股票代码、年份范围
**输出**：`data/reports/{股票代码}/1_pdf/` 目录下的 PDF 文件路径列表

---

## 步骤 2：PDF 转 Markdown

- 用 **pdf-to-markdown** 技能将步骤 1 下载的 PDF 逐个转换为 Markdown 格式, 保存位置为 `data/reports/{股票代码}/2_markdown/{年份}/`
- **每次委派只处理一个文件**。父Agent 循环执行：检查缺失的年份 → 委派单个文件 → 等待完成并验证 → 处理下一个
- 已有 `.md` 文件则跳过
- 禁止一次委派多个文件，否则子Agent 只会处理第一个

**输入**：步骤 1 输出的 PDF 路径列表
**输出**：`data/reports/{股票代码}/2_markdown/{年份}/` 目录下的 `.md` 文件路径列表

---

## 步骤 3：财报章节切割

- 用 **split-financial-report** 技能将步骤 2 的每个 `.md` 文件按章节目录切割为独立章节文件,切割文件保存路径为`data/reports/{股票代码}/3_split/{年份}/`
- **每次委派只处理一个文件**。父Agent 循环执行：检查缺失的年份 → 委派单个文件 → 等待完成并验证 → 处理下一个
- 已有切割结果则跳过
- 禁止一次委派多个文件

**输入**：步骤 2 输出的 `.md` 文件路径列表
**输出**：`data/reports/{股票代码}/3_split/{年份}/` 目录下的切割文件列表

---

## 步骤 4：财务排雷分析

用 **a-share-financial-forensic** 技能基于步骤 3 切割后的章节文件执行完整的财务排雷分析。

**委派策略**：一次委派覆盖所有年份。`a-share-financial-forensic` 技能内部已支持多年模式（阶段〇年份检测），不要按年份拆分为多次委派——那样会导致子Agent各自为战、无法跨年对比。

委派指令必须包含：
- 股票代码
- `{split_dir}` 路径（指向 `data/reports/{code}/3_split/`）
- 要求覆盖的年份范围（如已有切割目录则全部覆盖）

**输入**：步骤 3 输出的 `data/reports/{code}/3_split/` 目录路径
**输出**：完整分析报告，保存于 `data/reports/{code}/4_output/{code}_{year_from}-{year_to}_财务排雷分析报告.md`

---

## 步骤 4 降级策略

如果步骤 4 委派失败（token 预算不足或执行错误），父 Agent 应直接执行简化版排雷分析：
1. 用 run_command 从切割文件中提取三张核心报表的关键数据（合并资产负债表、合并利润表、合并现金流量表）
2. 对照 a-share-financial-forensic 技能的核心规则，覆盖最重要的检查项：
   - 审计意见（R019）
   - 存贷双高（R010：货币资金 vs 有息负债）
   - 受限资金占比及组成（R012）
   - 应收账款增速 vs 营收增速（R001/R002）+ 账龄趋势（R003：1年以上增长率）
   - 存货周转趋势 + 毛利率联动（R005/R007）
   - 经营现金流/净利润比值（R013）
   - 商誉减值迹象（R008/R009）
   - 大股东质押比例及年度趋势（R021）
   - 非经常性损益占比（R016）
3. 输出简化版分析报告，在报告末尾标注"本报告为降级模式输出，覆盖核心风险项，部分深度检查项未执行"

---

## 数据流

```
用户输入（股票名称/代码）
  → 步骤1: PDF 文件（data/reports/{code}/1_pdf/{year}/*.pdf）
    → 步骤2: Markdown 文件（data/reports/{code}/2_markdown/{year}/*.md）
      → 步骤3: 切割文件（data/reports/{code}/3_split/{year}/*.md）
        → 步骤4: 排雷报告 (data/reports/{code}/4_output/{code}_{year_from}-{year_to}_财务排雷分析报告.md)
```


## 增量策略

每一步都遵循"先检查已有产物 → 仅处理缺失部分"原则：
- 步骤1：已有 PDF → 跳过下载
- 步骤2：已有 `.md` → 跳过转换
- 步骤3：已有切割目录 → 跳过切割
- 步骤4：始终执行（分析基于最新数据）
