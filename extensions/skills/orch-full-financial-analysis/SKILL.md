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

**核心规则：每个步骤必须先调用 `Skill(name="子技能名")` 加载完整指令，然后严格按子技能的指令执行。** 不要跳过 Skill 调用直接在 orch 上下文中执行——子技能包含关键的边界条件处理，缺失会导致结果出错。

串行执行以下 4 个步骤，每步完成后再进入下一步。任一步骤失败时停止并报告用户。

## 前置确认

执行前确认以下信息（用户未明确提供时主动询问）：
- **股票名称或代码**（必填）
- **报告年份范围**（默认：近 3 年完整年报）
- **报告类型**（默认：年报，非摘要）

---

## 步骤 1：下载财报 PDF

```
Skill(name="download-a-share-reports")
```

按子技能指令下载指定年份的财报 PDF。遵循增量策略：已有文件跳过，仅下载缺失年份。

**输入**：股票代码、年份范围
**输出**：`data/reports/pdf/{股票代码}/` 目录下的 PDF 文件路径列表

---

## 步骤 2：PDF 转 Markdown

```
Skill(name="pdf-to-markdown")
```

按子技能指令将步骤 1 的每个 PDF 转换为 Markdown。已有 `.md` 文件则跳过。

**输入**：步骤 1 输出的 PDF 路径列表
**输出**：`data/reports/pdf/{股票代码}/` 目录下的 `.pdf.md` 文件路径列表

---

## 步骤 3：财报章节切割

```
Skill(name="split-financial-report")
```

按子技能指令将步骤 2 的每个 `.md` 文件按章节目录切割为独立章节文件。已有切割结果则跳过。

**输入**：步骤 2 输出的 `.md` 文件路径列表
**输出**：`data/reports/split/{股票代码}/` 目录下的切割文件列表

---

## 步骤 4：财务排雷分析

```
Skill(name="a-share-financial-forensic")
```

按子技能指令基于步骤 3 切割后的章节文件执行完整的财务排雷分析。每次均需执行（分析基于最新数据）。

**输入**：步骤 3 输出的切割文件目录路径
**输出**：结构化排雷分析报告

---

## 数据流

```
用户输入（股票名称/代码）
  → 步骤1: PDF 文件（data/reports/pdf/{code}/*.pdf）
    → 步骤2: Markdown 文件（data/reports/pdf/{code}/*.md）
      → 步骤3: 切割文件（data/reports/split/{code}/*.md）
        → 步骤4: 排雷报告
```

## 增量策略

每一步都遵循"先检查已有产物 → 仅处理缺失部分"原则：
- 步骤1：已有 PDF → 跳过下载
- 步骤2：已有 `.md` → 跳过转换
- 步骤3：已有切割目录 → 跳过切割
- 步骤4：始终执行（分析需基于最新数据）
