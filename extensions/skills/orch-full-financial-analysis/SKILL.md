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

串行执行以下 4 个步骤，每步完成后再进入下一步。任一步骤失败时停止并报告用户。

## 前置确认

执行前确认以下信息（用户未明确提供时主动询问）：
- **股票名称或代码**（必填）
- **报告年份范围**（默认：近 3 年完整年报）
- **报告类型**（默认：年报，非摘要）

---

## 步骤 1：下载财报 PDF

加载子技能：

```
Skill(name="download-a-share-reports")
```

### 1.1 增量下载（避免重复）

**先检查本地已有文件**，用 `run_command` 列出目标目录：

```bash
ls data/reports/pdf/{股票代码}/
```

对比所需年份和已有文件：
- 已有年份 → **跳过**，直接记录文件路径
- 缺失年份 → 仅下载缺失年份的 PDF

示例：用户要分析茅台 2023-2025 年报，目录下已有 `600519_2024.pdf`，则只下载 2023 和 2025 年。

### 1.2 执行下载

仅对缺失年份调用下载脚本：

```bash
cd extensions/skills/download-a-share-reports/scripts && \
  python download_report.py --stock {代码} --start {缺失起始年} --end {缺失结束年} \
    --category 年报 --save-dir data/reports/pdf
```

### 1.3 汇总

执行后汇总全部 PDF 文件路径（已有 + 新下载），供步骤 2 使用。

---

## 步骤 2：PDF 转 Markdown

加载子技能：

```
Skill(name="pdf-to-markdown")
```

对步骤 1 汇总的**每个 PDF** 检查对应 `.md` 是否已存在：

```bash
ls {pdf路径}.md
```

- 已存在 → 跳过转换
- 不存在 → 执行转换（财报 PDF 为电子文档，用快速模式 pdfplumber）

```bash
cd extensions/skills/pdf-to-markdown && \
  python3 scripts/pdf2markdown_fast.py {pdf路径} -o {pdf路径}.md
```

记录每个 `.md` 文件路径，供步骤 3 使用。

---

## 步骤 3：财报章节切割

加载子技能：

```
Skill(name="split-financial-report")
```

对步骤 2 输出的**每个 `.md` 文件**执行切割：

- 输出目录：`data/reports/split/{股票代码}/`
- 已存在切割结果目录且文件数正确 → 跳过
- 按 7 步流程操作（发现目录 → 提取标题 → 匹配行号 → 消歧 → 切割 → 验证 → 二次切割）
- 年报最后一章通常为"财务报告"，需执行第 7 步二次切割为 6 个子部分

记录切割后的目录路径和文件列表，供步骤 4 使用。

---

## 步骤 4：财务排雷分析

加载子技能：

```
Skill(name="a-share-financial-forensic")
```

基于步骤 3 切割后的财报章节文件，按 7 阶段流程分析：
1. 基础审查（审计意见、事务所变更、高管变动）
2. 资产负债表分析（逐科目排查）
3. 利润表分析（收入质量、毛利率、费用结构）
4. 现金流量表分析（现金净含量、8 种现金流量肖像）
5. 三表联动交叉验证
6. 附注反证
7. 综合定级

最终输出结构化排雷报告，使用 `references/report-template.md` 模板。

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
