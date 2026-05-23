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

- 用 **pdf-to-markdown** 技能将步骤 1 下载的每个 PDF 文件转换为 Markdown 格式, 保存位置为 `data/reports/{股票代码}/2_markdown/{年份}/`
- 已有 `.md` 文件则跳过

**输入**：步骤 1 输出的 PDF 路径列表
**输出**：`data/reports/{股票代码}/2_markdown/{年份}/` 目录下的 `.md` 文件路径列表

---

## 步骤 3：财报章节切割

- 用 **split-financial-report** 技能将步骤 2 的每个 `.md` 文件按章节目录切割为独立章节文件,切割文件保存路径为`data/reports/{股票代码}/3_split/{年份}/`
- 已有切割结果则跳过

**输入**：步骤 2 输出的 `.md` 文件路径列表
**输出**：`data/reports/{股票代码}/3_split/{年份}/` 目录下的切割文件列表

---

## 步骤 4：财务排雷分析

用 **a-share-financial-forensic** 技能基于步骤 3 切割后的章节文件执行完整的财务排雷分析。每次均需执行（分析基于最新数据）。

**输入**：步骤 3 输出的切割文件目录路径
**输出**：结构化排雷分析报告

---

## 报告输出

将 **步骤4**输出的报告写入本地： `data/reports/{code}/4_output/{股票代码}_{年份或年份范围}_财务分析报告.md`

---

## 数据流

```
用户输入（股票名称/代码）
  → 步骤1: PDF 文件（data/reports/{code}/1_pdf/{year}/*.pdf）
    → 步骤2: Markdown 文件（data/reports/{code}/2_markdown/{year}/*.md）
      → 步骤3: 切割文件（data/reports/{code}/3_split/{year}/*.md）
        → 步骤4: 排雷报告 (data/reports/{code}/4_output/{股票代码}_{年份或年份范围}_财务分析报告.md)
```


## 增量策略

每一步都遵循"先检查已有产物 → 仅处理缺失部分"原则：
- 步骤1：已有 PDF → 跳过下载
- 步骤2：已有 `.md` → 跳过转换
- 步骤3：已有切割目录 → 跳过切割
- 步骤4：始终执行（分析基于最新数据）
